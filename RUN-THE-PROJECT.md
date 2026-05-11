# RUN-THE-PROJECT

## Correr localmente

```powershell
cd "lca-ai-stack/source/ui"
npm run start:win
```

Abre en `http://localhost:3000`. No necesitas levantar ningún backend — todo está en AWS (Cognito, AppSync, S3).

## Subir cambios a producción

> Todos los comandos deben correrse en **PowerShell** (no en CMD ni Git Bash).

Si es la primera vez, habilita la ejecución de scripts (solo una vez):

```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Luego, autentícate con SSO y corre el script:

```powershell
aws sso login --profile connect-lab
cd "lca-ai-stack/source/ui"
$env:AWS_PROFILE = "connect-lab"
.\deploy-ui.ps1
```

El script compila, sube a S3 e invalida el caché de CloudFront automáticamente.

## Guardar cambios en el repositorio

Commit y push normal a la rama `develop`:

```powershell
git add .
git commit -m "tu mensaje"
git push origin develop
```
