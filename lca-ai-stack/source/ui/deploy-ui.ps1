$S3_BUCKET = "lca-poc-copilot-aistack-1y2o3j3mdoh6r-webappbucket-ymag6ijlvdsm"
$CLOUDFRONT_ID = "EOYQR4RH2MEO6"

Write-Host "Building UI..."
npm run build:win
if ($LASTEXITCODE -ne 0) { Write-Host "Build failed." -ForegroundColor Red; exit 1 }

Write-Host "Uploading to S3..."
aws s3 sync build/ "s3://$S3_BUCKET" --delete
if ($LASTEXITCODE -ne 0) { Write-Host "S3 sync failed." -ForegroundColor Red; exit 1 }

Write-Host "Invalidating CloudFront cache..."
aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_ID --paths "/*"

Write-Host "Done. Changes live at: https://$(aws cloudfront get-distribution --id $CLOUDFRONT_ID --query 'Distribution.DomainName' --output text)" -ForegroundColor Green
