<?php
require_once __DIR__ . '/config.php';
initErrorHandling(); setSecurityHeaders(); setHtmlNoCacheHeaders();
$settings=getUserSettings(); $baseUrl=getBaseUrl();
if(isset($_GET['save'])){
    rememberUserSettings($settings);
    setcookie(\RetroWEB\UserSettings::COOKIE,\RetroWEB\UserSettings::serialise($settings),[
        'expires'=>time()+31536000,'path'=>getBasePath()==='/'?'/':getBasePath().'/','secure'=>false,'httponly'=>true,'samesite'=>'Lax']);
    $destination=settingsReturnUrl($_GET['return']??null,$settings)
        ?? buildRetroWebUrl('index.php',\RetroWEB\UserSettings::query($settings));
    sendHttp10Response(302); header('Location: '.$destination); exit;
}
$e=fn($v)=>htmlspecialchars((string)$v,ENT_QUOTES|ENT_SUBSTITUTE,'ISO-8859-1');
$sel=fn($a,$v)=>(string)$a===(string)$v?' selected':'';
$html="<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 2.0//EN\">\n<html><head><title>RetroWEB Settings</title></head><body>\n".renderNavigation($settings['image_mode']);
$html.='<h1>RetroWEB Settings</h1><form method="get" action="'.$e($baseUrl.'/settings.php').'"><input type="hidden" name="save" value="1">';
if(settingsReturnUrl($_GET['return']??null,$settings)!==null)$html.='<input type="hidden" name="return" value="'.$e($_GET['return']).'">';
$html.='<p><b>Browser profile</b><br><select name="profile"><option value="auto"'.$sel($settings['profile'],'auto').'>Automatic</option>';
foreach(\RetroWEB\DeviceProfiles::all() as $id=>$p)$html.='<option value="'.$e($id).'"'.$sel($settings['profile'],$id).'>'.$e($p['label']).'</option>';
$html.='</select></p><p><b>Images</b><br><select name="img"><option value="links"'.$sel($settings['image_mode'],'links').'>As links</option><option value="inline"'.$sel($settings['image_mode'],'inline').'>Inline</option></select></p>';
$html.='<p><b>Maximum image size</b><br>Width: <input name="iw" size="5" value="'.$e($settings['image_width']).'"> Height: <input name="ih" size="5" value="'.$e($settings['image_height']).'"></p>';
$html.='<p><b>Page memory budget</b><br><select name="page_size">'; foreach(\RetroWEB\UserSettings::pageSizes() as $n)$html.='<option value="'.$n.'"'.$sel($settings['page_size'],$n).'>'.($n===0?'Unsplit':number_format($n).' bytes').'</option>'; $html.='</select><br><small>Includes HTML plus an estimate for inline image pixels.</small></p>';
$html.='<p><b>Maximum inline images</b><br><select name="page_images"><option value="all"'.$sel($settings['page_images'],-1).'>All images</option>'; for($n=0;$n<=10;$n++)$html.='<option value="'.$n.'"'.$sel($settings['page_images'],$n).'>'.$n.'</option>'; $html.='</select></p>';
$html.='<p><b>Tables</b><br><select name="tables">'; foreach(['auto'=>'Automatic','table'=>'Classic table','linearise'=>'Linear text'] as $v=>$l)$html.='<option value="'.$v.'"'.$sel($settings['tables'],$v).'>'.$l.'</option>'; $html.='</select><br><small>Classic tables use old HTML attributes and no section wrappers.</small></p>';
$html.='<p><b>Page layout</b><br><select name="layout">'; foreach(['auto'=>'Automatic','flow'=>'Single column','table'=>'Grid/Flex as tables'] as $v=>$l)$html.='<option value="'.$v.'"'.$sel($settings['layout'],$v).'>'.$l.'</option>'; $html.='</select><br><small>Only explicit CSS Grid and horizontal Flex layouts are converted.</small></p>';
$html.='<p><input type="submit" value="Save settings"></p></form><hr>';
$html.=renderForwardProxyNotice();
$html.='</body></html>';
sendHttp10Response(200); header('Content-Type: text/html; charset=iso-8859-1'); setHttp10Headers(strlen($html)); echo $html;
