Write-Host "Starting SupplierShield..." -ForegroundColor Cyan

# Kill anything on 8000
$existing = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($existing) {
    $existing | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

# Start backend in a new window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'd:\SupplierShieldAI\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload" -WindowStyle Normal

Start-Sleep -Seconds 3

# Start frontend in a new window  
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'd:\SupplierShieldAI\frontend'; npm run dev" -WindowStyle Normal

Write-Host ""
Write-Host "Backend:  http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Frontend: http://localhost:5173"  -ForegroundColor Green
