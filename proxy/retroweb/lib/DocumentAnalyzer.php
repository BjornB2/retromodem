<?php

namespace RetroWEB;

final class DocumentAnalyzer
{
    public static function analyse(string $html): array
    {
        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8">' . $html, LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return ['classification'=>'generic','confidence'=>'low','metrics'=>[]];
        $xpath = new \DOMXPath($dom);
        $count = fn(string $query): int => $xpath->query($query)->length;
        $metrics = [
            'main_regions'=>$count('//main | //*[@role="main"]'),
            'articles'=>$count('//article'), 'sections'=>$count('//main//section'),
            'headings'=>$count('//h1 | //h2 | //h3'), 'paragraphs'=>$count('//p'),
            'links'=>$count('//a[@href]'), 'forms'=>$count('//form'),
            'navigation_regions'=>$count('//nav | //*[@role="navigation"]'),
        ];
        $text = strtolower(trim(preg_replace('/\s+/', ' ', $dom->textContent)));
        $searchForms = $count('//form[.//input[contains(translate(@type,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"search")]
            or contains(translate(@role,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"search")]');
        $liveSignals = $count('//*[@aria-live or contains(concat(" ",normalize-space(@class)," ")," live ")]');
        if ($liveSignals > 0 || (str_contains($text, 'live') && $count('//time') >= 2)) {
            $classification = 'live-feed'; $confidence = 'high';
        } elseif ($searchForms > 0 && $metrics['links'] >= 3) {
            $classification = 'search-results'; $confidence = 'high';
        } elseif ($metrics['sections'] >= 2 && $metrics['links'] >= 5) {
            $classification = 'overview'; $confidence = 'high';
        } elseif ($metrics['articles'] === 1 || ($count('//h1') >= 1 && $metrics['paragraphs'] >= 2)) {
            $classification = 'article'; $confidence = 'high';
        } elseif ($metrics['links'] >= 8 && $metrics['paragraphs'] < 3) {
            $classification = 'overview'; $confidence = 'medium';
        } else {
            $classification = 'generic'; $confidence = 'medium';
        }
        return compact('classification', 'confidence', 'metrics');
    }
}
