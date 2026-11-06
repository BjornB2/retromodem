<?php

namespace RetroWEB;

final class LegacyHtmlSanitizer
{
    private const ATTRIBUTES = [
        'a'=>['href','name','id','title'],
        'img'=>['src','alt','title','width','height','data-rm-link-label','data-rm-pixels'],
        'p'=>['id','align'], 'blockquote'=>['id','cite'],
        'h1'=>['id','align'], 'h2'=>['id','align'], 'h3'=>['id','align'],
        'h4'=>['id','align'], 'h5'=>['id','align'], 'h6'=>['id','align'],
        'font'=>['color','face','size'],
        'ol'=>['id','start','type'], 'ul'=>['id','type'], 'li'=>['id','value','type'],
        'table'=>['id','border','cellpadding','cellspacing','width','height','align','bgcolor'],
        'caption'=>['id','align'], 'tr'=>['id','align','valign','bgcolor'],
        'td'=>['id','colspan','rowspan','width','height','align','valign','bgcolor','nowrap'],
        'th'=>['id','colspan','rowspan','width','height','align','valign','bgcolor','nowrap'],
        'form'=>['action','method'],
        'input'=>['type','name','value','checked','size','maxlength'],
        'select'=>['name','size','multiple'], 'option'=>['value','selected'],
        'textarea'=>['name','rows','cols'], 'label'=>['for'],
        'pre'=>['id','width'], 'hr'=>['id','align','width','size','noshade'],
        'q'=>['id','cite'], 'address'=>['id'], 'dl'=>['id'], 'dt'=>['id'], 'dd'=>['id'],
    ];

    public static function removeHiddenContent(string $html): string
    {
        [$dom, $root] = self::fragment($html);
        if (!$root) return $html;
        $xpath = new \DOMXPath($dom);
        $nodes = [];
        $query = './/*[@hidden or translate(@aria-hidden,"TRUE","true")="true"'
            . ' or contains(translate(@style,"ABCDEFGHIJKLMNOPQRSTUVWXYZ ","abcdefghijklmnopqrstuvwxyz"),"display:none")'
            . ' or contains(translate(@style,"ABCDEFGHIJKLMNOPQRSTUVWXYZ ","abcdefghijklmnopqrstuvwxyz"),"visibility:hidden")]';
        foreach ($xpath->query($query, $root) as $node) $nodes[] = $node;
        foreach ($nodes as $node) if ($node->parentNode) $node->parentNode->removeChild($node);
        return self::innerHtml($dom, $root);
    }

    public static function sanitiseAttributes(string $html): string
    {
        [$dom, $root] = self::fragment($html);
        if (!$root) return $html;
        $elements = [];
        foreach ($root->getElementsByTagName('*') as $element) $elements[] = $element;
        foreach ($elements as $element) {
            $tag = strtolower($element->tagName);
            $allowed = self::ATTRIBUTES[$tag] ?? ['id'];
            foreach (iterator_to_array($element->attributes) as $attribute) {
                $name = strtolower($attribute->name);
                if (!in_array($name, $allowed, true) || !self::valid($name, $attribute->value)) {
                    $element->removeAttributeNode($attribute);
                }
            }
        }
        return self::innerHtml($dom, $root);
    }

    private static function valid(string $name, string $value): bool
    {
        if ($name === 'href' || $name === 'src' || $name === 'cite') {
            $decoded = trim(html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8'));
            return $decoded !== '' && !preg_match('/^(?:javascript|data|vbscript):/i', $decoded);
        }
        if (in_array($name, ['border','cellpadding','cellspacing','colspan','rowspan','start','value','data-rm-pixels'], true)) {
            return preg_match('/^[0-9]{1,8}$/', $value) === 1;
        }
        if (in_array($name, ['width','height'], true)) return preg_match('/^[0-9]{1,5}%?$/', $value) === 1;
        if ($name === 'align') return in_array(strtolower($value), ['left','center','right','justify','char','top','middle','bottom'], true);
        if ($name === 'valign') return in_array(strtolower($value), ['top','middle','bottom','baseline'], true);
        if ($name === 'bgcolor' || $name === 'color') return preg_match('/^(?:#[0-9a-f]{3,6}|[a-z]{1,20})$/i', $value) === 1;
        if ($name === 'size') return preg_match('/^[+-]?[1-7]$/', $value) === 1;
        return strlen($value) <= 2048;
    }

    private static function fragment(string $html): array
    {
        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8"><div id="retroweb-sanitizer-root">' . $html . '</div>', LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return [$dom, null];
        $root = (new \DOMXPath($dom))->query('//*[@id="retroweb-sanitizer-root"]')->item(0);
        return [$dom, $root];
    }

    private static function innerHtml(\DOMDocument $dom, \DOMNode $node): string
    {
        $html = '';
        foreach ($node->childNodes as $child) $html .= $dom->saveHTML($child);
        return $html;
    }
}
