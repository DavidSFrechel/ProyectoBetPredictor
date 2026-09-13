<?php
declare(strict_types=1);
if ($_SERVER['REQUEST_METHOD'] !== 'POST') { header('Location: clasificacion_partidos.php', true, 303); exit; }
$python = 'C:\\Users\\dsfre\\AppData\\Local\\Programs\\Python\\Python312\\python.exe';
$script = 'C:\\David\\Personal\\ProyectoBetPredictor\\refresh_partidos.py';
$log = __DIR__ . DIRECTORY_SEPARATOR . 'refresh_partidos.log';
if (!is_file($python) || !is_file($script)) { http_response_code(500); exit('No se encontró Python o refresh_partidos.py.'); }
$output = shell_exec(escapeshellarg($python) . ' ' . escapeshellarg($script) . ' 2>&1');
file_put_contents($log, date('c') . "\n" . $output . "\n", FILE_APPEND | LOCK_EX);
header('Location: clasificacion_partidos.php?refrescado=1', true, 303);
exit;
