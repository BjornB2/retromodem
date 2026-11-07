<?php
/** RetroWEB public aggregate statistics. */

require_once __DIR__ . '/config.php';
initErrorHandling();
setSecurityHeaders();
setHtmlNoCacheHeaders();

$stats = getPublicStats();
$baseUrl = getBaseUrl();
$windowMinutes = max(1, (int)ceil($stats['window_seconds'] / 60));

$html = "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 2.0//EN\">\n";
$html .= "<html><head><title>RetroWEB statistics</title></head><body>\n";
$html .= '<p><a href="' . htmlspecialchars($baseUrl . '/index.php', ENT_QUOTES, 'ISO-8859-1') . '">RetroWEB</a></p>' . "\n";
$html .= "<h1>Public statistics</h1>\n";
$html .= "<dl>\n";
$html .= '<dt>Total pageviews</dt><dd>' . formatNumber($stats['total_pageviews']) . "</dd>\n";
$html .= '<dt>Approximate visits</dt><dd>' . formatNumber($stats['unique_visitors']) . "</dd>\n";
$html .= '<dt>Visitors in the last ' . $windowMinutes . ' minutes</dt><dd>' . formatNumber($stats['active_visitors']) . "</dd>\n";
$html .= '<dt>Processed pages</dt><dd>' . formatNumber($stats['processed_pages']) . "</dd>\n";
$html .= '<dt>Processed images</dt><dd>' . formatNumber($stats['processed_images']) . "</dd>\n";
$html .= '<dt>Successful processing requests</dt><dd>' . formatNumber($stats['processing_success']) . "</dd>\n";
$html .= '<dt>Processing errors</dt><dd>' . formatNumber($stats['processing_error']) . "</dd>\n";
$html .= "</dl>\n";
$html .= "<h2>Processing time</h2><ul>\n";
$html .= '<li>Under 0.5 seconds: ' . formatNumber($stats['processing_under_500ms']) . "</li>\n";
$html .= '<li>0.5 to 2 seconds: ' . formatNumber($stats['processing_under_2s']) . "</li>\n";
$html .= '<li>Over 2 seconds: ' . formatNumber($stats['processing_over_2s']) . "</li>\n</ul>\n";
if (!empty($stats['profiles'])) {
    $html .= "<h2>Device profiles</h2><ul>\n";
    foreach ($stats['profiles'] as $profile=>$count) $html .= '<li>' . htmlspecialchars($profile, ENT_QUOTES, 'ISO-8859-1') . ': ' . formatNumber($count) . "</li>\n";
    $html .= "</ul>\n";
}
$html .= "<h2>Privacy</h2>\n";
$html .= "<p>These are aggregate counters. This page does not publish visited URLs, search terms, form data or visitor identifiers.</p>\n";
$html .= "<p>Visitor addresses are stored only as hashes for the short counting window and are not displayed.</p>\n";
$html .= "</body></html>\n";
$html = prepareLegacyBrowserHtml($html, getUserSettings());

sendHttp10Response(200);
header('Content-Type: text/html; charset=iso-8859-1');
setHttp10Headers(strlen($html));
echo $html;
