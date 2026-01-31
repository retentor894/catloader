#!/usr/bin/env node

/**
 * CatLoader GitHub Webhook Server
 *
 * Escucha webhooks de GitHub y ejecuta deployment automatico cuando:
 * - Push a main → Redeploy produccion
 * - Push a dev → Redeploy desarrollo
 *
 * Configuracion requerida:
 * - CATLOADER_WEBHOOK_SECRET: Secret configurado en GitHub webhook
 * - CATLOADER_WEBHOOK_PORT: Puerto donde escuchar (default: 9001)
 */

const http = require('http');
const crypto = require('crypto');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// Configuracion
const PORT = process.env.CATLOADER_WEBHOOK_PORT || 9001;
const SECRET = process.env.CATLOADER_WEBHOOK_SECRET;
const LOG_FILE = process.env.CATLOADER_WEBHOOK_LOG ||
  (process.env.HOME ? `${process.env.HOME}/catloader-production/logs/webhook.log` : '/tmp/catloader-webhook.log');

// Request limits
const MAX_BODY_SIZE = parseInt(process.env.MAX_BODY_SIZE) || 10 * 1024 * 1024;
const REQUEST_TIMEOUT = parseInt(process.env.REQUEST_TIMEOUT) || 30000;
const DEPLOY_TIMEOUT = parseInt(process.env.DEPLOY_TIMEOUT) || 600000; // 10 minutes

// Ensure log directory exists
const logDir = path.dirname(LOG_FILE);
try {
  if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir, { recursive: true, mode: 0o755 });
    console.log(`[${new Date().toISOString()}] Created log directory: ${logDir}`);
  }
} catch (error) {
  console.error(`[${new Date().toISOString()}] FATAL: Cannot create log directory ${logDir}: ${error.message}`);
  process.exit(1);
}

// Deployment queue
const deploymentQueue = {
  prod: { running: false, queued: [] },
  dev: { running: false, queued: [] }
};

// Metrics tracking
const metrics = {
  totalRequests: 0,
  totalDeployments: 0,
  successfulDeployments: 0,
  failedDeployments: 0,
  startTime: new Date()
};

// Colors for logs
const COLORS = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  blue: '\x1b[34m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
};

function log(message, color = 'reset') {
  const timestamp = new Date().toISOString();
  const coloredMsg = `${COLORS[color]}[${timestamp}] ${message}${COLORS.reset}`;
  console.log(coloredMsg);

  const plainMsg = `[${timestamp}] ${message}\n`;
  fs.appendFile(LOG_FILE, plainMsg, (error) => {
    if (error) {
      console.error(`[${timestamp}] Failed to write to log file: ${error.message}`);
    }
  });
}

function verifySignature(payload, signature) {
  if (!signature || typeof signature !== 'string') {
    log('Missing or invalid X-Hub-Signature-256 header', 'red');
    return false;
  }

  if (!signature.startsWith('sha256=')) {
    log('Invalid signature format (missing sha256= prefix)', 'red');
    return false;
  }

  const hmac = crypto.createHmac('sha256', SECRET);
  const digest = 'sha256=' + hmac.update(payload).digest('hex');

  if (signature.length !== digest.length) {
    log('Signature length mismatch', 'red');
    return false;
  }

  try {
    return crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(digest)
    );
  } catch (error) {
    log(`Signature comparison error: ${error.message}`, 'red');
    return false;
  }
}

function executeDeployment(branch, repoPath) {
  return new Promise((resolve, reject) => {
    log(`Starting deployment for branch: ${branch}`, 'blue');

    const scriptPath = path.join(repoPath, 'scripts', 'deploy.sh');

    if (!fs.existsSync(scriptPath)) {
      return reject(new Error(`Deploy script not found: ${scriptPath}`));
    }

    const deploy = spawn('bash', [scriptPath], {
      cwd: repoPath,
      env: {
        ...process.env,
        PATH: process.env.PATH,
        AUTOMATED_DEPLOY: 'true'
      }
    });

    const timeoutId = setTimeout(() => {
      log(`Deployment timeout for ${branch} after ${DEPLOY_TIMEOUT}ms`, 'red');
      deploy.kill('SIGTERM');
      setTimeout(() => deploy.kill('SIGKILL'), 10000);
      reject(new Error(`Deployment timeout after ${DEPLOY_TIMEOUT}ms`));
    }, DEPLOY_TIMEOUT);

    let output = '';

    deploy.stdout.on('data', (data) => {
      const text = data.toString();
      output += text;
      process.stdout.write(text);
    });

    deploy.stderr.on('data', (data) => {
      const text = data.toString();
      output += text;
      process.stderr.write(text);
    });

    deploy.on('close', (code) => {
      clearTimeout(timeoutId);
      if (code === 0) {
        log(`Deployment completed successfully for ${branch}`, 'green');
        resolve(output);
      } else {
        log(`Deployment failed for ${branch} with code ${code}`, 'red');
        reject(new Error(`Deployment failed with exit code ${code}`));
      }
    });

    deploy.on('error', (err) => {
      clearTimeout(timeoutId);
      log(`Deployment error for ${branch}: ${err.message}`, 'red');
      reject(err);
    });
  });
}

function queueDeployment(branch, repoPath) {
  const env = branch === 'main' ? 'prod' : 'dev';

  return new Promise((resolve, reject) => {
    const deployTask = { branch, repoPath, resolve, reject };

    if (deploymentQueue[env].running) {
      log(`Deployment for ${branch} queued (another deployment in progress)`, 'yellow');
      deploymentQueue[env].queued.push(deployTask);
    } else {
      processDeployment(deployTask, env);
    }
  });
}

function processDeployment(deployTask, env) {
  deploymentQueue[env].running = true;
  metrics.totalDeployments++;

  executeDeployment(deployTask.branch, deployTask.repoPath)
    .then((result) => {
      deployTask.resolve(result);
      deploymentQueue[env].running = false;
      metrics.successfulDeployments++;

      if (deploymentQueue[env].queued.length > 0) {
        const next = deploymentQueue[env].queued.shift();
        log(`Processing queued deployment for ${next.branch}`, 'blue');
        processDeployment(next, env);
      }
    })
    .catch((err) => {
      deployTask.reject(err);
      deploymentQueue[env].running = false;
      metrics.failedDeployments++;

      if (deploymentQueue[env].queued.length > 0) {
        const next = deploymentQueue[env].queued.shift();
        log(`Processing queued deployment for ${next.branch}`, 'blue');
        processDeployment(next, env);
      }
    });
}

function handleWebhook(payload) {
  try {
    const event = JSON.parse(payload);

    if (!event.ref) {
      log('Ignoring non-push event', 'yellow');
      return { status: 'ignored', reason: 'not a push event' };
    }

    const branch = event.ref.replace('refs/heads/', '');
    const commits = event.commits || [];

    log(`Received push to ${branch} with ${commits.length} commit(s)`, 'blue');

    let repoPath = null;

    if (branch === 'main') {
      repoPath = process.env.CATLOADER_PROD_PATH || '/home/raptor/catloader-production/app';
      log('Deploying to PRODUCTION', 'yellow');
    } else if (branch === 'dev') {
      repoPath = process.env.CATLOADER_DEV_PATH || '/home/raptor/catloader-development/app';
      log('Deploying to DEVELOPMENT', 'blue');
    } else {
      log(`Ignoring push to branch: ${branch}`, 'yellow');
      return { status: 'ignored', reason: `branch ${branch} not configured for deployment` };
    }

    if (!fs.existsSync(repoPath)) {
      log(`Repository path does not exist: ${repoPath}`, 'red');
      return { status: 'error', error: `Repository not found: ${repoPath}` };
    }

    if (!fs.existsSync(path.join(repoPath, '.git'))) {
      log(`Not a git repository: ${repoPath}`, 'red');
      return { status: 'error', error: `Not a git repository: ${repoPath}` };
    }

    queueDeployment(branch, repoPath)
      .then(() => log(`Auto-deployment completed for ${branch}`, 'green'))
      .catch(err => log(`Auto-deployment failed for ${branch}: ${err.message}`, 'red'));

    return { status: 'accepted', branch, commits: commits.length };

  } catch (error) {
    log(`Error processing webhook: ${error.message}`, 'red');
    return { status: 'error', error: error.message };
  }
}

// Create HTTP server
const server = http.createServer((req, res) => {
  metrics.totalRequests++;

  // Health check endpoint
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'healthy',
      service: 'catloader-webhook',
      uptime: process.uptime(),
      timestamp: new Date().toISOString(),
      deploymentQueue: {
        prod: {
          running: deploymentQueue.prod.running,
          queued: deploymentQueue.prod.queued.length
        },
        dev: {
          running: deploymentQueue.dev.running,
          queued: deploymentQueue.dev.queued.length
        }
      }
    }));
    return;
  }

  // Metrics endpoint
  if (req.method === 'GET' && req.url === '/metrics') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      totalRequests: metrics.totalRequests,
      totalDeployments: metrics.totalDeployments,
      successfulDeployments: metrics.successfulDeployments,
      failedDeployments: metrics.failedDeployments,
      successRate: metrics.totalDeployments > 0
        ? ((metrics.successfulDeployments / metrics.totalDeployments) * 100).toFixed(2) + '%'
        : 'N/A',
      uptime: Math.floor(process.uptime()),
      startTime: metrics.startTime
    }));
    return;
  }

  // Webhook endpoint
  if (req.method !== 'POST' || req.url !== '/webhook') {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
    return;
  }

  req.setTimeout(REQUEST_TIMEOUT, () => {
    log('Request timeout', 'red');
    if (!res.headersSent) {
      res.writeHead(408, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Request timeout' }));
    }
    req.destroy();
  });

  let body = '';
  let bodySize = 0;

  req.on('data', (chunk) => {
    bodySize += chunk.length;

    if (bodySize > MAX_BODY_SIZE) {
      log(`Request body too large: ${bodySize} bytes`, 'red');
      res.writeHead(413, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Request body too large' }));
      req.destroy();
      return;
    }

    body += chunk.toString();
  });

  req.on('end', () => {
    const signature = req.headers['x-hub-signature-256'];

    if (!verifySignature(body, signature)) {
      log('Invalid signature received', 'red');
      res.writeHead(401, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid signature' }));
      return;
    }

    const result = handleWebhook(body);

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result));
  });
});

// Validate secret at startup
if (!SECRET || SECRET.length < 32) {
  console.error('\x1b[31m%s\x1b[0m', 'FATAL: CATLOADER_WEBHOOK_SECRET not set or too short (minimum 32 characters)');
  console.error('\x1b[33m%s\x1b[0m', 'Generate a secure secret with: openssl rand -hex 32');
  console.error('\x1b[33m%s\x1b[0m', 'Then set it as environment variable: export CATLOADER_WEBHOOK_SECRET=your-secret');
  process.exit(1);
}

const BIND_ADDRESS = process.env.BIND_ADDRESS || '127.0.0.1';

// Start server
server.listen(PORT, BIND_ADDRESS, () => {
  log(`CatLoader Webhook Server listening on ${BIND_ADDRESS}:${PORT}`, 'green');
  log(`Log file: ${LOG_FILE}`, 'blue');
  log(`CATLOADER_WEBHOOK_SECRET validated (${SECRET.length} chars)`, 'green');
});

// Error handling
process.on('uncaughtException', (err) => {
  log(`Uncaught exception: ${err.message}`, 'red');
  console.error(err.stack);
});

process.on('unhandledRejection', (reason, promise) => {
  log(`Unhandled rejection: ${reason}`, 'red');
});
