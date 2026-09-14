<?php
declare(strict_types=1);

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    exit('Método no permitido.');
}

$league = trim((string) ($_POST['league'] ?? ''));
$match = trim((string) ($_POST['match'] ?? ''));
if ($match === '' || mb_strlen($match) > 200) {
    http_response_code(400);
    exit('Partido no válido.');
}

$python = 'C:\\Users\\dsfre\\AppData\\Local\\Programs\\Python\\Python312\\python.exe';
$script = __DIR__ . DIRECTORY_SEPARATOR . 'estadisticas_ultimos_cinco_mobile.py';
if (!is_file($python) || !is_file($script)) {
    http_response_code(500);
    exit('No se encontró Python o el script de estadísticas.');
}

set_time_limit(180);
$command = escapeshellarg($python) . ' ' . escapeshellarg($script) . ' --inline ' . escapeshellarg($league) . ' ' . escapeshellarg($match) . ' 2>&1';
$output = shell_exec($command);
if ($output === null || $output === '') {
    $output = 'El proceso no produjo salida. Revisa la conectividad con Flashscore.';
}
?>
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Estadísticas: <?= htmlspecialchars($match, ENT_QUOTES, 'UTF-8') ?></title>
<style>body{font-family:Arial,sans-serif;margin:18px;background:#f6f7fb;color:#111}h1{font-size:20px}pre{white-space:pre-wrap;word-break:break-word;background:#202124;color:#e8eaed;padding:16px;border-radius:8px;line-height:1.4}</style></head>
<body><h1>Estadísticas: <?= htmlspecialchars($match, ENT_QUOTES, 'UTF-8') ?></h1><pre><?= htmlspecialchars($output, ENT_QUOTES, 'UTF-8') ?></pre></body></html>
