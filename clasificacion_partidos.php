<?php
declare(strict_types=1);

$txtFile = __DIR__ . DIRECTORY_SEPARATOR . 'partidos_agrupados.txt';
$groups = [];
$activeGroup = null;
$loadError = '';

if (is_readable($txtFile)) {
    $lines = preg_split('/\r?\n/', (string) file_get_contents($txtFile));
    foreach ($lines as $line) {
        $line = trim($line);
        if ($line === '') continue;
        if (preg_match('/^Bloque:\s*(.+)$/iu', $line, $block)) {
            $groups[] = ['name' => 'Bloque: ' . trim($block[1]), 'matches' => []];
            $activeGroup = count($groups) - 1;
            continue;
        }
        if ($activeGroup === null) continue;
        if (preg_match('/^-\s*\[([^\]]+)\]\s*(\d{1,2}:\d{2})\s+(.+?)\s*\(id:\s*([^\)]+)\)\s*(?:\(odds:\s*([0-9.]+)\/([0-9.]+)\/([0-9.]+)\))?$/u', $line, $match)) {
            $groups[$activeGroup]['matches'][] = [
                'league' => trim($match[1]), 'time' => $match[2], 'match' => trim($match[3]),
                'odds' => ['1' => isset($match[5]) ? (float) $match[5] : 0.0, 'X' => isset($match[6]) ? (float) $match[6] : 0.0, '2' => isset($match[7]) ? (float) $match[7] : 0.0],
            ];
        }
    }
    if (!$groups) $loadError = 'El archivo no contiene bloques de partidos reconocibles.';
} else {
    $loadError = 'Todavía no existe partidos_agrupados.txt. Pulsa «Refrescar partidos hoy».';
}

function classify(array $odds): array {
    if ($odds['1'] <= 0 || $odds['X'] <= 0 || $odds['2'] <= 0) return ['-', '-'];
    if ($odds['1'] < 1.5) return ['T1', 'Local'];
    if ($odds['2'] < 1.5) return ['T1', 'Visitante'];
    if ($odds['1'] > 1.5 && $odds['1'] < 1.95) return ['T2', 'Local'];
    if ($odds['2'] > 1.5 && $odds['2'] < 1.95) return ['T2', 'Visitante'];
    return ['T3', '-'];
}
?>
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Clasificación de partidos por cuotas</title>
<style>body{font-family:Arial,Helvetica,sans-serif;padding:20px;background:#f7f7f7}table{border-collapse:collapse;width:100%;background:#fff}th,td{padding:8px;border:1px solid #ddd;text-align:left}th{background:#222;color:#fff}.T1{background:#c8e6c9}.T2{background:#fff9c4}.T3{background:#ffcdd2}.notice{padding:10px;background:#fff3cd;border:1px solid #ffe69c}.source{color:#555;font-size:.9em}</style>
</head><body>
<h1>Clasificación de partidos por cuotas (1 / X / 2)</h1>
<form method="post" action="refresh_partidos.php"><button type="submit">Refrescar partidos hoy</button></form>
<p>Reglas: T1 = cuota &lt; 1.5; T2 = cuota entre 1.5 y 1.95; resto = T3.</p>
<?php if ($loadError): ?><p class="notice"><?= htmlspecialchars($loadError, ENT_QUOTES, 'UTF-8') ?></p><?php endif; ?>
<?php foreach ($groups as $group): ?>
<h2><?= htmlspecialchars($group['name'], ENT_QUOTES, 'UTF-8') ?></h2><table><thead><tr><th>Hora</th><th>Liga</th><th>Partido</th><th>1</th><th>X</th><th>2</th><th>Tipo</th><th>Dirección</th><th>Estadísticas</th></tr></thead><tbody>
<?php foreach ($group['matches'] as $m): [$type, $side] = classify($m['odds']); ?>
<tr<?= $type !== '-' ? ' class="' . $type . '"' : '' ?>><td><?= htmlspecialchars($m['time'], ENT_QUOTES, 'UTF-8') ?></td><td><?= htmlspecialchars($m['league'], ENT_QUOTES, 'UTF-8') ?></td><td><?= htmlspecialchars($m['match'], ENT_QUOTES, 'UTF-8') ?></td><td><?= $m['odds']['1'] ? number_format($m['odds']['1'], 2) : '—' ?></td><td><?= $m['odds']['X'] ? number_format($m['odds']['X'], 2) : '—' ?></td><td><?= $m['odds']['2'] ? number_format($m['odds']['2'], 2) : '—' ?></td><td><?= $type ?></td><td><?= $side ?></td><td><form method="post" action="run_stats.php" target="stats_popup" onsubmit="window.open('', 'stats_popup', 'width=1100,height=800,scrollbars=yes,resizable=yes')"><input type="hidden" name="league" value="<?= htmlspecialchars($m['league'], ENT_QUOTES, 'UTF-8') ?>"><input type="hidden" name="match" value="<?= htmlspecialchars($m['match'], ENT_QUOTES, 'UTF-8') ?>"><button type="submit">Ver estadísticas</button></form></td></tr>
<?php endforeach; ?></tbody></table>
<?php endforeach; ?>
<?php if (is_readable($txtFile)): ?><p class="source">Archivo origen: <strong>partidos_agrupados.txt</strong> · actualizado: <?= date('Y-m-d H:i:s', filemtime($txtFile)) ?></p><?php endif; ?>
</body></html>
