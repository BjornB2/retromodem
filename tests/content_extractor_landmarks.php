<?php
// Focused regression for overview-page landmarks and nested headline articles.
require_once __DIR__ . '/../proxy/retroweb/lib/ContentExtractor.php';

function check($condition, $message) {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

$padding = str_repeat('Useful page content. ', 20);
$extractor = new RetroWEB\CustomDOMExtractor();
foreach (['<main>', '<div role="main">'] as $opening) {
    $closing = $opening === '<main>' ? '</main>' : '</div>';
    $html = '<html><head><title>Overview</title></head><body>'
        . '<nav>Outside navigation</nav>' . $opening
        . '<h2>Featured story</h2><p>' . $padding . '</p>'
        . '<article>Grouped updates<article>Nested headline</article></article>'
        . $closing . '<aside>Outside sidebar</aside></body></html>';
    $result = $extractor->extract($html);
    check(strpos($result['content'], 'Featured story') !== false, 'Main content before headlines was lost');
    check(substr_count($result['content'], 'Nested headline') === 1, 'Nested headline was duplicated');
    check(strpos($result['content'], 'Outside navigation') === false, 'Outside navigation was included');
    check(strpos($result['content'], 'Outside sidebar') === false, 'Outside sidebar was included');
}

$result = $extractor->extract('<html><body><article><p>' . $padding
    . '</p><article>Nested article</article></article></body></html>');
check(substr_count($result['content'], 'Nested article') === 1, 'Article fallback duplicates nested articles');

$result = $extractor->extract('<html><body><main><div role="main"><p>' . $padding
    . '</p>Nested landmark</div></main></body></html>');
check(substr_count($result['content'], 'Nested landmark') === 1, 'Nested main landmarks were duplicated');
echo "PASS content extractor landmarks\n";
