<?php

namespace RetroWEB;

final class DeviceProfiles
{
    private const PROFILES = [
        'generic' => [
            'label' => 'Generic legacy browser',
            'html' => 'html32',
            'image_width' => 320,
            'image_height' => 240,
            'page_size' => 500000,
            'page_images' => 8,
            'tables' => 'auto',
            'layout' => 'auto',
        ],
        'macweb' => [
            'label' => 'MacWeb',
            'html' => 'html20',
            'image_width' => 320,
            'image_height' => 240,
            'page_size' => 100000,
            'page_images' => 4,
            'tables' => 'linearise',
            'layout' => 'flow',
        ],
        'psion' => [
            'label' => 'Psion/EPOC Web',
            'html' => 'html32',
            'image_width' => 480,
            'image_height' => 240,
            'page_size' => 250000,
            'page_images' => 6,
            'tables' => 'auto',
            'layout' => 'flow',
        ],
        'psion5mx' => [
            'label' => 'Psion Series 5mx',
            'html' => 'html32',
            'image_mode' => 'inline',
            'image_width' => 600,
            'image_height' => 240,
            'page_size' => 500000,
            'page_images' => 10,
            'tables' => 'auto',
            'layout' => 'flow',
        ],
        'palm' => [
            'label' => 'Palm browser',
            'html' => 'html32',
            'image_width' => 160,
            'image_height' => 160,
            'page_size' => 250000,
            'page_images' => 5,
            'tables' => 'linearise',
            'layout' => 'flow',
        ],
        'nokia9210' => [
            'label' => 'Nokia 9210/9210i',
            'html' => 'html32',
            'image_mode' => 'inline',
            'image_width' => 480,
            'image_height' => 200,
            'page_size' => 500000,
            'page_images' => 10,
            'tables' => 'auto',
            'layout' => 'flow',
        ],
        'ie_win98' => [
            'label' => 'Internet Explorer on Windows 98',
            'html' => 'html4-lite',
            'image_mode' => 'inline',
            'image_width' => 640,
            'image_height' => 480,
            'page_size' => 1250000,
            'page_images' => 10,
            'tables' => 'table',
            'layout' => 'table',
        ],
        'text' => [
            'label' => 'Text only',
            'html' => 'html20',
            'image_width' => 0,
            'image_height' => 0,
            'page_size' => 250000,
            'page_images' => 0,
            'tables' => 'linearise',
            'layout' => 'flow',
        ],
    ];

    public static function all(): array
    {
        return self::PROFILES;
    }

    public static function get(string $id): array
    {
        return self::PROFILES[$id] ?? self::PROFILES['generic'];
    }

    public static function storageGeneration(string $id): string
    {
        return match ($id) {
            'generic' => 'generic:2',
            'macweb' => 'macweb:2',
            'psion' => 'psion:2',
            'psion5mx' => 'psion5mx:1',
            'nokia9210' => 'nokia9210:3',
            'palm' => 'palm:3',
            'ie_win98' => 'ie_win98:2',
            'text' => 'text:2',
            default => $id,
        };
    }

    public static function detect(?string $userAgent): array
    {
        $userAgent = trim((string)$userAgent);
        if ($userAgent === '') {
            return self::result('generic', 'none', 'No User-Agent header received');
        }

        if (preg_match('/(?:Nokia[\s\/-]?92(?:10|11)|Nokia\/Series-92(?:00|10|11)|Crystal\/6\.0)/i', $userAgent)) {
            return self::result('nokia9210', 'high', 'Nokia 92xx or Symbian Crystal identifier');
        }
        if (stripos($userAgent, 'RetroModem RetroWEB Proxy') !== false) {
            return self::result('nokia9210', 'medium', 'RetroModem legacy proxy identifier');
        }
        if (stripos($userAgent, 'MacWeb') !== false) {
            return self::result('macweb', 'high', 'MacWeb product identifier');
        }
        if (preg_match('/(?:PalmSource|Blazer[\s\/]|Xiino|PalmOS|Palm OS)/i', $userAgent)) {
            return self::result('palm', 'high', 'Palm browser or platform identifier');
        }
        if (preg_match('/(?:Series[\s\/-]?5mx|Psion[^;)]*5mx|\b5mx\b|\bMC218\b)/i', $userAgent)) {
            return self::result('psion5mx', 'high', 'Psion Series 5mx or Ericsson MC218 identifier');
        }
        if (preg_match('/(?:EPOC32-WTL|STNC-WTL|\bEPOC\b|\bPsion\b)/i', $userAgent)) {
            return self::result('psion', 'medium', 'EPOC, STNC or Psion identifier');
        }
        if (preg_match('/MSIE\s+[3-6](?:\.\d+)?/i', $userAgent)
            && preg_match('/(?:Windows 98|Win98)/i', $userAgent)) {
            return self::result('ie_win98', 'high', 'Internet Explorer and Windows 98 identifiers');
        }

        return self::result('generic', 'low', 'No supported legacy browser identifier matched');
    }

    private static function result(string $id, string $confidence, string $reason): array
    {
        return [
            'id' => $id,
            'profile' => self::get($id),
            'confidence' => $confidence,
            'reason' => $reason,
        ];
    }
}
