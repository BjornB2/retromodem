<?php

namespace RetroWEB;

final class LegacyFormConverter
{
    private const PREFIX = 'rwf_';

    public static function rewrite(string $html, string $pageUrl, string $proxyUrl, array $settings): string
    {
        if (stripos($html, '<form') === false) return $html;
        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8"><div id="retroweb-form-root">' . $html . '</div>', LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return $html;
        $xpath = new \DOMXPath($dom);
        $root = $xpath->query('//*[@id="retroweb-form-root"]')->item(0);
        if (!$root) return $html;

        $forms = [];
        foreach ($xpath->query('.//form', $root) as $form) $forms[] = $form;
        foreach ($forms as $form) {
            if (!$form instanceof \DOMElement || !$form->parentNode) continue;
            $sensitive = $xpath->query('.//input[translate(@type,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="password"'
                . ' or translate(@type,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="file"]', $form);
            if ($sensitive->length > 0) {
                $warning = $dom->createElement('p');
                $bold = $dom->createElement('b', 'Form not supported: ');
                $warning->appendChild($bold);
                $warning->appendChild($dom->createTextNode('passwords and file uploads are disabled because the browser connection uses HTTP.'));
                $form->parentNode->replaceChild($warning, $form);
                continue;
            }

            $action = trim($form->getAttribute('action'));
            $action = self::absoluteUrl($action !== '' ? $action : $pageUrl, $pageUrl);
            if ($action === null) {
                $form->parentNode->removeChild($form);
                continue;
            }
            $method = strtolower($form->getAttribute('method')) === 'post' ? 'post' : 'get';
            while ($form->attributes->length) $form->removeAttributeNode($form->attributes->item(0));
            $form->setAttribute('action', $proxyUrl);
            $form->setAttribute('method', $method);
            self::hidden($dom, $form, 'url', $action);
            foreach (UserSettings::query($settings) as $name => $value) self::hidden($dom, $form, $name, (string)$value);

            $controls = [];
            foreach ($xpath->query('.//input | .//select | .//textarea | .//button', $form) as $control) $controls[] = $control;
            foreach ($controls as $index => $control) {
                if (!$control instanceof \DOMElement) continue;
                $name = $control->getAttribute('name');
                if ($name !== '') $control->setAttribute('name', self::encodeName($name, $index));
                if (strtolower($control->tagName) === 'input') {
                    $type = strtolower($control->getAttribute('type'));
                    if (!in_array($type, ['hidden','text','checkbox','radio','submit','reset'], true)) $control->setAttribute('type', 'text');
                } elseif (strtolower($control->tagName) === 'button') {
                    $input = $dom->createElement('input');
                    $input->setAttribute('type', 'submit');
                    $input->setAttribute('value', trim($control->textContent) ?: 'Submit');
                    if ($control->hasAttribute('name')) $input->setAttribute('name', $control->getAttribute('name'));
                    if ($control->hasAttribute('value')) $input->setAttribute('value', $control->getAttribute('value'));
                    $control->parentNode->replaceChild($input, $control);
                }
            }
        }
        return self::innerHtml($dom, $root);
    }

    public static function submittedFields(array $input): array
    {
        $fields = [];
        foreach ($input as $name => $value) {
            if (!is_string($name) || !str_starts_with($name, self::PREFIX)) continue;
            $decoded = self::decodeName($name);
            if ($decoded === null || (!is_scalar($value) && !is_array($value))) continue;
            if (array_key_exists($decoded, $fields)) {
                if (!is_array($fields[$decoded])) $fields[$decoded] = [$fields[$decoded]];
                foreach ((array)$value as $item) $fields[$decoded][] = $item;
            } else {
                $fields[$decoded] = $value;
            }
        }
        return $fields;
    }

    public static function encodeFields(array $fields): string
    {
        $pairs = [];
        foreach ($fields as $name => $value) {
            if (!is_string($name)) continue;
            foreach ((array)$value as $item) {
                if (is_scalar($item)) $pairs[] = rawurlencode($name) . '=' . rawurlencode((string)$item);
            }
        }
        return implode('&', $pairs);
    }

    private static function encodeName(string $name, int $index): string
    {
        return self::PREFIX . rtrim(strtr(base64_encode($name), '+/', '-_'), '=') . '__' . $index;
    }

    private static function decodeName(string $name): ?string
    {
        $encoded = substr($name, strlen(self::PREFIX));
        $encoded = preg_replace('/__\d+$/', '', $encoded);
        if ($encoded === '' || !preg_match('/^[A-Za-z0-9_-]+$/', $encoded)) return null;
        $decoded = base64_decode(strtr($encoded, '-_', '+/'), true);
        return is_string($decoded) && $decoded !== '' && strlen($decoded) <= 256 ? $decoded : null;
    }

    private static function hidden(\DOMDocument $dom, \DOMElement $form, string $name, string $value): void
    {
        $input = $dom->createElement('input');
        $input->setAttribute('type', 'hidden');
        $input->setAttribute('name', $name);
        $input->setAttribute('value', $value);
        $form->insertBefore($input, $form->firstChild);
    }

    private static function absoluteUrl(string $url, string $base): ?string
    {
        $url = html_entity_decode(trim($url), ENT_QUOTES | ENT_HTML5, 'UTF-8');
        if (preg_match('/^https?:\/\//i', $url)) return $url;
        if ($url === '' || str_starts_with($url, '#') || preg_match('/^(?:javascript|data|mailto):/i', $url)) return null;
        $parts = parse_url($base);
        if (!isset($parts['scheme'], $parts['host'])) return null;
        if (str_starts_with($url, '//')) return $parts['scheme'] . ':' . $url;
        $origin = $parts['scheme'] . '://' . $parts['host'] . (isset($parts['port']) ? ':' . $parts['port'] : '');
        if (str_starts_with($url, '/')) return $origin . $url;
        $path = isset($parts['path']) ? dirname($parts['path']) : '/';
        $segments = explode('/', trim($path . '/' . $url, '/'));
        $normal = [];
        foreach ($segments as $segment) {
            if ($segment === '' || $segment === '.') continue;
            if ($segment === '..') array_pop($normal); else $normal[] = $segment;
        }
        return $origin . '/' . implode('/', $normal);
    }

    private static function innerHtml(\DOMDocument $dom, \DOMNode $node): string
    {
        $html = '';
        foreach ($node->childNodes as $child) $html .= $dom->saveHTML($child);
        return $html;
    }
}
