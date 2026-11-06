<?php
/**
 * RetroWEB - Error Handler voor HTTP/1.0 Browsers
 * Onderschept 400 en 404 errors van Apache en normaliseert de request
 * Dit script wordt aangeroepen wanneer Apache een 400 (Bad Request) of 404 (Not Found) error geeft
 * voor requests zonder Host header (zoals MacWeb 2.0)
 */

// VROEGE REQUEST NORMALISATIE (VOOR ALLES ANDERS)
// Dit is cruciaal voor HTTP/1.0 browsers zoals MacWeb 2.0 die geen Host header sturen
if (empty($_SERVER['HTTP_HOST']) && !empty($_SERVER['SERVER_NAME'])) {
    $_SERVER['HTTP_HOST'] = $_SERVER['SERVER_NAME'];
    if (!empty($_SERVER['SERVER_PORT']) && $_SERVER['SERVER_PORT'] != 80 && $_SERVER['SERVER_PORT'] != 443) {
        $_SERVER['HTTP_HOST'] .= ':' . $_SERVER['SERVER_PORT'];
    }
}

// Zorg dat REQUEST_URI beschikbaar is
if (empty($_SERVER['REQUEST_URI']) && !empty($_SERVER['SCRIPT_NAME'])) {
    $_SERVER['REQUEST_URI'] = $_SERVER['SCRIPT_NAME'];
    if (!empty($_SERVER['QUERY_STRING'])) {
        $_SERVER['REQUEST_URI'] .= '?' . $_SERVER['QUERY_STRING'];
    }
}

// Parse QUERY_STRING handmatig als $_GET leeg is
if (empty($_GET) && !empty($_SERVER['QUERY_STRING'])) {
    parse_str($_SERVER['QUERY_STRING'], $parsedGet);
    if (!empty($parsedGet)) {
        $_GET = array_merge($_GET, $parsedGet);
    }
}

// Bepaal het pad naar index.php (gebruik dezelfde logica als config.php)
// Dit is belangrijk voor subdirectory installaties
if (isset($_SERVER['SCRIPT_NAME']) && !empty($_SERVER['SCRIPT_NAME'])) {
    $basePath = rtrim(dirname($_SERVER['SCRIPT_NAME']), '/') ?: '/';
} else {
    $basePath = '/';
}

// Als we via ErrorDocument zijn aangeroepen, probeer de base path te bepalen
// op basis van waar error_handler.php daadwerkelijk staat
$scriptDir = __DIR__;
$documentRoot = isset($_SERVER['DOCUMENT_ROOT']) ? $_SERVER['DOCUMENT_ROOT'] : '';
if (!empty($documentRoot) && strpos($scriptDir, $documentRoot) === 0) {
    // Bereken base path op basis van fysieke locatie
    $relativePath = str_replace($documentRoot, '', $scriptDir);
    $relativePath = str_replace('\\', '/', $relativePath); // Windows compatibility
    $calculatedBasePath = rtrim($relativePath, '/') ?: '/';
    
    // Gebruik de berekende base path als deze logischer lijkt
    if ($calculatedBasePath !== '/' && $basePath === '/') {
        $basePath = $calculatedBasePath;
    }
}

// Bepaal de oorspronkelijke request URI
// Als ErrorDocument wordt gebruikt, kan de oorspronkelijke URI in REDIRECT_URL staan
$originalUri = '/';
if (!empty($_SERVER['REDIRECT_URL'])) {
    // Apache ErrorDocument zet REDIRECT_URL (voor 400/404 errors)
    $originalUri = $_SERVER['REDIRECT_URL'];
} elseif (!empty($_SERVER['REQUEST_URI'])) {
    // Verwijder error_handler.php uit de URI
    $originalUri = str_replace('/error_handler.php', '', $_SERVER['REQUEST_URI']);
    $originalUri = str_replace('error_handler.php', '', $originalUri);
    
    // Als er een code parameter is, verwijder die ook
    $originalUri = preg_replace('/[?&]code=\d+/', '', $originalUri);
    
    // Verwijder query string voor path detectie
    $originalUri = preg_replace('/\?.*$/', '', $originalUri);
}

// Als de URI nog steeds error_handler.php bevat of leeg is, gebruik root
if (strpos($originalUri, 'error_handler.php') !== false || empty($originalUri) || $originalUri === '/') {
    $originalUri = '/';
}

// Als de URI leeg is of alleen /, gebruik index.php
if (empty($originalUri) || $originalUri === '/' || $originalUri === $basePath || $originalUri === $basePath . '/') {
    $targetFile = 'index.php';
    $originalUri = '/';
} else {
    // Bepaal naar welk bestand we moeten doorsturen op basis van het pad
    if (preg_match('/\/proxy\.php/', $originalUri) || preg_match('/proxy\.php/', $originalUri)) {
        $targetFile = 'proxy.php';
    } elseif (preg_match('/\/image_cruncher\.php/', $originalUri) || preg_match('/image_cruncher\.php/', $originalUri)) {
        $targetFile = 'image_cruncher.php';
    } elseif (preg_match('/\/search_engine\.php/', $originalUri) || preg_match('/search_engine\.php/', $originalUri)) {
        $targetFile = 'search_engine.php';
    } else {
        // Default naar index.php
        $targetFile = 'index.php';
    }
}

// Bouw de redirect URL
if ($basePath === '/') {
    $redirectUrl = '/' . $targetFile;
} else {
    $redirectUrl = $basePath . '/' . $targetFile;
}

// Behoud query string parameters (behalve code parameter)
// Gebruik REDIRECT_QUERY_STRING als die beschikbaar is (van ErrorDocument)
$queryString = '';
if (!empty($_SERVER['REDIRECT_QUERY_STRING'])) {
    $queryString = $_SERVER['REDIRECT_QUERY_STRING'];
} elseif (!empty($_SERVER['QUERY_STRING'])) {
    $queryString = $_SERVER['QUERY_STRING'];
}

// Verwijder code parameter uit query string
$queryString = preg_replace('/[?&]code=\d+/', '', $queryString);
$queryString = preg_replace('/^&/', '', $queryString);

// Voeg query string toe aan redirect URL
if (!empty($queryString)) {
    $redirectUrl .= '?' . $queryString;
}

// Stuur HTTP/1.0 response en redirect
header('HTTP/1.0 302 Found');
header('Location: ' . $redirectUrl);
header('Connection: close');
exit;
