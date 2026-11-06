<?php

namespace RetroWEB;

final class LegacyDomRenderer
{
    private const BASE_TAGS = [
        'a','ol','ul','li','br','p','small','font','b','strong','i','em','blockquote',
        'h1','h2','h3','h4','h5','h6','img','form','input','select','option','textarea',
        'label','pre','code','samp','kbd','var','tt','dl','dt','dd','hr','address','cite',
        'q','strike','u','del','ins','mark',
    ];
    private const TABLE_TAGS = ['table','caption','tr','th','td','thead','tbody','tfoot'];
    private const DROP_WITH_CONTENT = ['script','style','noscript','template','iframe','object','embed','svg','canvas'];

    public static function render(string $html, bool $allowTables): string
    {
        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8"><div id="retroweb-render-root">' . $html . '</div>', LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return '';
        $root = (new \DOMXPath($dom))->query('//*[@id="retroweb-render-root"]')->item(0);
        if (!$root) return '';
        $allowed = array_fill_keys(array_merge(self::BASE_TAGS, $allowTables ? self::TABLE_TAGS : []), true);
        $elements = iterator_to_array($root->getElementsByTagName('*'));
        foreach (array_reverse($elements) as $element) {
            if (!$element instanceof \DOMElement || !$element->parentNode) continue;
            $tag = strtolower($element->tagName);
            if (isset($allowed[$tag])) continue;
            if (in_array($tag, self::DROP_WITH_CONTENT, true)) {
                $element->parentNode->removeChild($element);
                continue;
            }
            while ($element->firstChild) $element->parentNode->insertBefore($element->firstChild, $element);
            $element->parentNode->removeChild($element);
        }
        $images = iterator_to_array($root->getElementsByTagName('img'));
        foreach ($images as $image) {
            if (!$image instanceof \DOMElement || !$image->parentNode) continue;
            $next = $image->nextSibling;
            while ($next instanceof \DOMText && trim($next->textContent) === '') $next = $next->nextSibling;
            if ($next instanceof \DOMText && trim($next->textContent) !== ''
                || $next instanceof \DOMElement && !in_array(strtolower($next->tagName), ['br','p','div','section','article','ul','ol','table','h1','h2','h3','h4','h5','h6'], true)) {
                $image->parentNode->insertBefore($dom->createElement('br'), $image->nextSibling);
            }
        }
        return LegacyHtmlSanitizer::sanitiseAttributes(self::innerHtml($dom, $root));
    }

    private static function innerHtml(\DOMDocument $dom, \DOMNode $node): string
    {
        $html = '';
        foreach ($node->childNodes as $child) $html .= $dom->saveHTML($child);
        return $html;
    }
}
