<?php
namespace RetroWEB;

final class UserSettings
{
    public const COOKIE = 'retroweb_settings';
    private const PAGE_SIZES = [0,12000,18000,25000,50000,75000,100000,125000,150000,175000,200000,250000,500000,750000,1000000,1250000,1500000,1750000,2000000];

    public static function resolve(array $query, array $cookies, ?string $userAgent, array $serverSession = []): array
    {
        $stored = [];
        if (isset($cookies[self::COOKIE]) && is_string($cookies[self::COOKIE])) parse_str($cookies[self::COOKIE], $stored);
        $stored = array_replace($stored, $serverSession);
        $detection = DeviceProfiles::detect($userAgent);
        $preliminary = array_replace($stored, $query);
        $requestedProfile = isset($preliminary['profile']) && is_string($preliminary['profile']) ? $preliminary['profile'] : 'auto';
        if ($requestedProfile !== 'auto' && !isset(DeviceProfiles::all()[$requestedProfile])) $requestedProfile = 'auto';
        $preliminaryResolved = $requestedProfile === 'auto' ? $detection['id'] : $requestedProfile;
        $preliminaryDefaults = DeviceProfiles::get($preliminaryResolved);
        $currentBindingStorage = ($stored['_profile_bindings'] ?? null) === '3';
        $profileImageMode = array_key_exists('profile_img', $query)
            ? $query['profile_img'] === '1'
            : ($currentBindingStorage
                ? ($stored['profile_img'] ?? null) === '1'
                : !isset($stored['img']) || $stored['img'] === ($preliminaryDefaults['image_mode'] ?? 'links'));
        $profileImageSize = array_key_exists('profile_size', $query)
            ? $query['profile_size'] === '1'
            : ($currentBindingStorage
                ? ($stored['profile_size'] ?? null) === '1'
                : ((!isset($stored['iw']) || (int)$stored['iw'] === (int)$preliminaryDefaults['image_width'])
                    && (!isset($stored['ih']) || (int)$stored['ih'] === (int)$preliminaryDefaults['image_height'])));
        // On the settings form, checked profile bindings deliberately ignore
        // the simultaneously submitted manual image controls.
        if (($query['save'] ?? null) === '1') {
            if ($profileImageMode) unset($query['img']);
            if ($profileImageSize) unset($query['iw'], $query['ih']);
        }
        if ($profileImageMode && !array_key_exists('img', $query)) unset($stored['img']);
        if ($profileImageSize && !array_key_exists('iw', $query) && !array_key_exists('ih', $query)) {
            unset($stored['iw'], $stored['ih']);
        }
        if ($requestedProfile === 'auto' && ($stored['_resolved'] ?? '') !== DeviceProfiles::storageGeneration($detection['id'])) {
            // Stored automatic defaults belonged to another detected browser.
            // Refresh them, while explicit URL/form choices remain authoritative.
            foreach (['img','iw','ih','page_size','page_images','tables','layout'] as $name) {
                if (!array_key_exists($name, $query)) unset($stored[$name]);
            }
        }
        unset($stored['_resolved'], $stored['_profile_bindings']);
        $input = array_replace($stored, $query);
        $requested = isset($input['profile']) && is_string($input['profile']) ? $input['profile'] : 'auto';
        if ($requested !== 'auto' && !isset(DeviceProfiles::all()[$requested])) $requested = 'auto';
        $resolved = $requested === 'auto' ? $detection['id'] : $requested;
        $defaults = DeviceProfiles::get($resolved);
        return [
            'profile'=>$requested, 'resolved_profile'=>$resolved, 'profile_label'=>$defaults['label'],
            'automatic'=>$requested === 'auto', 'confidence'=>$detection['confidence'],
            'profile_image_mode'=>$profileImageMode, 'profile_image_size'=>$profileImageSize,
            'image_mode'=>self::choice($input['img']??null,['links','inline'],$defaults['image_mode']??'links'),
            'image_width'=>self::integer($input['iw']??null,0,1280,$defaults['image_width']),
            'image_height'=>self::integer($input['ih']??null,0,1280,$defaults['image_height']),
            'page_size'=>self::pageSize($input['page_size']??null,$defaults['page_size']),
            'page_images'=>self::imageLimit($input['page_images']??null,$defaults['page_images']),
            'tables'=>self::tableChoice($input['tables']??null,$defaults['tables']),
            'layout'=>self::choice($input['layout']??null,['auto','flow','table'],$defaults['layout']),
            'html'=>$defaults['html'],
        ];
    }
    public static function query(array $s, array $changes=[]): array {
        $query = [
            'profile'=>$s['profile'],
            'profile_img'=>!empty($s['profile_image_mode'])?'1':'0',
            'profile_size'=>!empty($s['profile_image_size'])?'1':'0',
            'page_size'=>(string)$s['page_size'],'page_images'=>$s['page_images'] === -1 ? 'all' : (string)$s['page_images'],
            'tables'=>$s['tables'],'layout'=>$s['layout']];
        if (empty($s['profile_image_mode'])) $query['img']=$s['image_mode'];
        if (empty($s['profile_image_size'])) {
            $query['iw']=(string)$s['image_width'];
            $query['ih']=(string)$s['image_height'];
        }
        return array_replace($query,$changes);
    }
    public static function serialise(array $s): string { return http_build_query(array_replace(self::query($s), [
        '_resolved'=>DeviceProfiles::storageGeneration($s['resolved_profile']), '_profile_bindings'=>'3'])); }
    public static function pageSizes(): array { return self::PAGE_SIZES; }
    private static function choice($v,array $a,string $d): string { return is_string($v)&&in_array($v,$a,true)?$v:$d; }
    private static function tableChoice($v,string $d): string { if($v==='keep'||$v==='simplify')return 'table'; return self::choice($v,['auto','table','linearise'],$d); }
    private static function integer($v,int $min,int $max,int $d): int { if(!is_scalar($v)||!preg_match('/^[0-9]+$/D',(string)$v))return $d; $v=(int)$v; return $v>=$min&&$v<=$max?$v:$d; }
    private static function imageLimit($v,int $d): int { if($v === 'all')return -1; return self::integer($v,0,10,$d); }
    private static function pageSize($v,int $d): int { if(!is_scalar($v)||!preg_match('/^[0-9]+$/D',(string)$v))return $d; $v=(int)$v; return in_array($v,self::PAGE_SIZES,true)?$v:$d; }
}
