<?php

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/lib/DeviceProfiles.php';

initErrorHandling();
setSecurityHeaders();
setHtmlNoCacheHeaders();

$userAgent = getClientUserAgent();
$detection = \RetroWEB\DeviceProfiles::detect($userAgent);
$profile = $detection['profile'];
$escape = static function ($value): string {
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'ISO-8859-1');
};

$html = "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 2.0//EN\">\n";
$html .= "<html><head><title>RetroWEB Client Info</title></head><body>\n";
$html .= renderNavigation(getImageMode());
$html .= "<h1>RetroWEB Client Info</h1>\n";
$html .= "<p>This page shows the current request only. It does not store these values.</p>\n";
$html .= "<dl>\n";
$html .= "<dt><b>Detected profile</b></dt><dd>" . $escape($profile['label']) . "</dd>\n";
$html .= "<dt><b>Confidence</b></dt><dd>" . $escape($detection['confidence']) . "</dd>\n";
$html .= "<dt><b>Reason</b></dt><dd>" . $escape($detection['reason']) . "</dd>\n";
$html .= "<dt><b>User-Agent</b></dt><dd><code>" . $escape($userAgent !== '' ? $userAgent : '(missing)') . "</code></dd>\n";
if (isset($_SERVER['HTTP_X_RETROMODEM_USER_AGENT'])) {
    $html .= "<dt><b>Transport User-Agent</b></dt><dd><code>" . $escape($_SERVER['HTTP_USER_AGENT'] ?? '(missing)') . "</code></dd>\n";
}
$html .= "<dt><b>HTTP version</b></dt><dd>" . $escape($_SERVER['SERVER_PROTOCOL'] ?? '(unknown)') . "</dd>\n";
$html .= "<dt><b>Accept</b></dt><dd><code>" . $escape($_SERVER['HTTP_ACCEPT'] ?? '(missing)') . "</code></dd>\n";
$html .= "<dt><b>Accept-Language</b></dt><dd><code>" . $escape($_SERVER['HTTP_ACCEPT_LANGUAGE'] ?? '(missing)') . "</code></dd>\n";
$html .= "</dl>\n";
$html .= "<h2>Profile defaults</h2>\n<ul>\n";
$html .= "<li>HTML: " . $escape($profile['html']) . "</li>\n";
$html .= "<li>Images: " . $escape($profile['image_mode'] ?? 'links') . "</li>\n";
$html .= "<li>Image size: " . $escape($profile['image_width']) . " x " . $escape($profile['image_height']) . "</li>\n";
$html .= "<li>Page size: " . $escape($profile['page_size']) . " bytes</li>\n";
$html .= "<li>Inline images per page: " . $escape($profile['page_images']) . "</li>\n";
$html .= "<li>Table mode: " . $escape($profile['tables']) . "</li>\n";
$html .= "</ul>\n</body></html>\n";
$html = prepareLegacyBrowserHtml($html, getUserSettings());

sendHttp10Response(200);
header('Content-Type: text/html; charset=iso-8859-1');
setHttp10Headers(strlen($html));
echo $html;

