<?php
// Backfill product aliases in the Bethany House hub from Neema's original
// catalogue. Matches hub products by SKU (exact) then English name (exact,
// case-insensitive) and sets `aliases` ONLY where currently empty — idempotent
// and non-destructive. Run inside the bethany_laravel container:
//   docker exec bethany_laravel php /tmp/backfill_aliases.php [--commit]

require '/var/www/vendor/autoload.php';
$app = require '/var/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Models\Product;
use Illuminate\Support\Facades\DB;

$commit = in_array('--commit', $argv);
$rows = json_decode(file_get_contents('/tmp/neema_aliases.json'), true);
if (!is_array($rows)) { fwrite(STDERR, "could not read /tmp/neema_aliases.json\n"); exit(1); }

$norm = fn($s) => preg_replace('/[^a-z0-9]/', '', strtolower((string)$s));

$bySku = [];  $byName = [];  $byNameNorm = [];  $byAliasNorm = [];
foreach ($rows as $r) {
    $al = array_values(array_filter(array_map('trim', $r['aliases'] ?? [])));
    if (!$al) continue;
    if (!empty($r['sku']))  $bySku[strtoupper(trim($r['sku']))]   = $al;
    if (!empty($r['name'])) {
        $byName[strtolower(trim($r['name']))] = $al;
        $byNameNorm[$norm($r['name'])] = $al;      // punctuation/space-insensitive
    }
    foreach ($al as $a) { $byAliasNorm[$norm($a)] = $al; }   // hub name == a Neema alias
}

$updated = 0; $skippedHasAliases = 0; $unmatched = [];
foreach (Product::all() as $p) {
    $name = DB::table('product_translations')
        ->where('product_id', $p->id)->where('language_code', 'en')->value('name');
    $sku  = $p->sku ? strtoupper(trim($p->sku)) : null;
    $nn   = $name ? $norm($name) : '';

    $al = null; $how = '';
    if ($sku && isset($bySku[$sku]))                         { $al = $bySku[$sku];        $how = 'sku'; }
    elseif ($name && isset($byName[strtolower(trim($name))])) { $al = $byName[strtolower(trim($name))]; $how = 'name'; }
    elseif ($nn && isset($byNameNorm[$nn]))                  { $al = $byNameNorm[$nn];    $how = 'name~'; }
    elseif ($nn && isset($byAliasNorm[$nn]))                 { $al = $byAliasNorm[$nn];   $how = 'alias='; }

    if ($al === null) { $unmatched[] = ($p->sku ?: '?') . " | " . ($name ?: '?'); continue; }

    $current = $p->aliases;
    if (is_array($current) && count($current) > 0) { $skippedHasAliases++; continue; }

    echo "MATCH[" . $how . "]  " . ($p->sku ?: '-') . " | " . $name . "  ->  [" . implode(', ', $al) . "]\n";
    if ($commit) { $p->aliases = $al; $p->save(); }
    $updated++;
}

echo "\n" . ($commit ? "COMMITTED" : "DRY-RUN") . ": would update {$updated} product(s); "
   . "{$skippedHasAliases} already had aliases; " . count($unmatched) . " unmatched.\n";
if ($unmatched) { echo "UNMATCHED hub products:\n  " . implode("\n  ", $unmatched) . "\n"; }
