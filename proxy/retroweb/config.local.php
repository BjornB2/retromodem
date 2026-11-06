<?php

/**
 * RetroModem deployment overrides for the bundled RetroWEB renderer.
 *
 * The local renderer is only reachable through the Python forward-proxy
 * adapter. Keep its generated links on the loopback endpoint so the adapter
 * can translate them back to legacy-browser routes.
 */

$readImageDimension = static function (string $key, string $legacy, int $fallback): int {
    $values = [];
    $path = getenv('RETROMODEM_CONFIG_FILE') ?: '/etc/retromodem/retromodem.env';
    foreach (@file($path, FILE_IGNORE_NEW_LINES) ?: [] as $line) {
        if (!preg_match('/^(RETROMODEM_(?:PROXY|68KPROXY)_IMAGE_(?:WIDTH|HEIGHT))=(.*)$/D', $line, $match)) {
            continue;
        }
        $value = trim($match[2], " \t\r\n\"'");
        if (ctype_digit($value) && (int) $value >= 16 && (int) $value <= 4096) {
            $values[$match[1]] = (int) $value;
        }
    }

    foreach ([$values[$key] ?? null, $values[$legacy] ?? null, getenv($key), getenv($legacy)] as $value) {
        if (is_numeric($value) && (int) $value >= 16 && (int) $value <= 4096) {
            return (int) $value;
        }
    }
    return $fallback;
};

return [
    'public_host' => '127.0.0.1:8090',
    'max_image_width' => $readImageDimension('RETROMODEM_PROXY_IMAGE_WIDTH', 'RETROMODEM_68KPROXY_IMAGE_WIDTH', 200),
    'max_image_height' => $readImageDimension('RETROMODEM_PROXY_IMAGE_HEIGHT', 'RETROMODEM_68KPROXY_IMAGE_HEIGHT', 150),
    'user_agent' => getenv('RETROMODEM_PROXY_USER_AGENT') ?: 'Mozilla/5.0 (compatible; RetroModem RetroWEB Proxy/1.0)',
    'rate_limit_enabled' => false,
    'visitor_tracking_enabled' => false,
];
