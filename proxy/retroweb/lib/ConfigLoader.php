<?php

namespace RetroWEB;

final class ConfigLoader
{
    public static function load(string $root): array
    {
        $defaults = require $root . '/config.defaults.php';
        if (!is_array($defaults)) {
            throw new \RuntimeException('config.defaults.php must return an array');
        }

        $localPath = $root . '/config.local.php';
        if (!is_file($localPath)) {
            return $defaults;
        }

        $local = require $localPath;
        if (!is_array($local)) {
            throw new \RuntimeException('config.local.php must return an array');
        }

        $unknown = array_diff_key($local, $defaults);
        if ($unknown) {
            throw new \RuntimeException('Unknown local configuration keys: ' . implode(', ', array_keys($unknown)));
        }

        return array_replace($defaults, $local);
    }
}

