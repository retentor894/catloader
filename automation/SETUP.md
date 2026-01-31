# CatLoader Webhook Auto-Deploy Setup

Este documento describe como configurar el auto-deploy de CatLoader via GitHub webhooks.

## Resumen

| Componente | Valor |
|------------|-------|
| Puerto webhook | 9001 |
| URL webhook | https://catloader-webhook.nidourbano.net/webhook |
| Secret | `b911e2a9a71482614a15ef3c073fa356ed49f8d7ae2adb90c1e1d6c1829706e7` |
| Ramas monitoreadas | `main` (prod), `dev` (dev) |

## Paso 1: Instalar servicio systemd

```bash
# Copiar el archivo de servicio
sudo cp /home/raptor/catloader-production/app/automation/catloader-webhook.service /etc/systemd/system/

# Recargar systemd
sudo systemctl daemon-reload

# Habilitar el servicio (iniciar automaticamente)
sudo systemctl enable catloader-webhook

# Iniciar el servicio
sudo systemctl start catloader-webhook

# Verificar estado
sudo systemctl status catloader-webhook
```

## Paso 2: Actualizar Cloudflare Tunnel

Agregar la siguiente linea al archivo `/etc/cloudflared/config.yml` **ANTES** de la linea `- service: http_status:404`:

```yaml
  # CatLoader Webhook
  - hostname: catloader-webhook.nidourbano.net
    service: http://localhost:9001
```

Luego reiniciar cloudflared:

```bash
sudo systemctl restart cloudflared
```

## Paso 3: Crear ruta DNS en Cloudflare

```bash
cloudflared tunnel route dns 695a644c-d7bc-43d3-a3a8-0b2fe1d6c603 catloader-webhook.nidourbano.net
```

## Paso 4: Configurar GitHub Webhook

1. Ir al repositorio de CatLoader en GitHub
2. Settings → Webhooks → Add webhook
3. Configurar:
   - **Payload URL**: `https://catloader-webhook.nidourbano.net/webhook`
   - **Content type**: `application/json`
   - **Secret**: `b911e2a9a71482614a15ef3c073fa356ed49f8d7ae2adb90c1e1d6c1829706e7`
   - **Which events**: Just the push event
   - **Active**: Checked

4. Guardar el webhook

## Paso 5: Verificar funcionamiento

```bash
# Ver logs del webhook server
sudo journalctl -u catloader-webhook -f

# Verificar health del servidor
curl http://localhost:9001/health

# Ver metricas
curl http://localhost:9001/metrics
```

## Paso 6: Probar el deploy

Hacer un push a la rama `dev` o `main` y verificar que el deploy se ejecuta automaticamente.

```bash
# En el repositorio local
git checkout dev
echo "# test" >> README.md
git add . && git commit -m "test webhook"
git push origin dev
```

Observar los logs:
```bash
sudo journalctl -u catloader-webhook -f
```

## Comandos utiles

```bash
# Ver estado del servicio
sudo systemctl status catloader-webhook

# Ver logs en tiempo real
sudo journalctl -u catloader-webhook -f

# Reiniciar servicio
sudo systemctl restart catloader-webhook

# Ver ultimos 100 logs
sudo journalctl -u catloader-webhook -n 100

# Ver historial de deployments
cat /home/raptor/catloader-production/logs/deploy-history.log
cat /home/raptor/catloader-development/logs/deploy-history.log
```

## Troubleshooting

### El webhook no recibe eventos
- Verificar que el DNS route existe: `cloudflared tunnel route dns list`
- Verificar que el servicio esta corriendo: `sudo systemctl status catloader-webhook`
- Verificar connectivity: `curl https://catloader-webhook.nidourbano.net/health`

### El deploy falla
- Verificar logs: `sudo journalctl -u catloader-webhook -f`
- Ejecutar deploy manualmente: `cd /home/raptor/catloader-production/app && ./scripts/deploy.sh`
- Verificar permisos: El script debe ser ejecutable

### Error de firma invalida
- Verificar que el secret en GitHub coincide con el del servicio systemd
- El secret debe tener exactamente 64 caracteres (32 bytes en hex)
