import unittest
from unittest.mock import patch
from web import web


class PaginationSettingsTests(unittest.TestCase):
    def test_larger_sizes_are_selectable_and_validated(self):
        for size in ('25000', '50000', '75000', '100000', '125000', '150000', '175000', '200000'):
            self.assertEqual(web.proxy_pagination_settings(size)['RETROMODEM_PROXY_PAGE_SIZE'], size)
            for language in ('nl', 'en'):
                page = web.proxy_settings_card(language, {'RETROMODEM_PROXY_PAGE_SIZE': size})
                self.assertIn(f'value="{size}" selected', page)
    def test_form_defaults_and_saved_choices_in_both_languages(self):
        for language in ('nl', 'en'):
            page = web.proxy_settings_card(language, {})
            self.assertIn('name="page_size"', page)
            self.assertIn('value="18000" selected', page)
            self.assertNotIn('name="page_images"', page)
            self.assertIn('name="image_start"', page)
            page = web.proxy_settings_card(language, {'RETROMODEM_PROXY_PAGE_SIZE': '0', 'RETROMODEM_PROXY_IMAGE_START': 'remember'})
            self.assertIn('value="0" selected', page)
            self.assertIn('value="remember" selected', page)

    def handler(self, size='12000', images='2'):
        handler = object.__new__(web.Handler)
        handler.path = '/settings/proxy'
        handler.headers = {}
        handler.config = lambda: {}
        handler.require_auth = lambda _: True
        handler.valid_csrf = lambda _: True
        handler.form = lambda: dict(mode='manual', image_mode='inline', exceptions='example.org',
                                    image_width='144', image_height='120', page_size=size, page_images=images)
        handler.redirect = lambda path: setattr(handler, 'location', path)
        handler.send_error = lambda status, *_: setattr(handler, 'error', status)
        return handler

    def test_save_persists_both_options_without_restarting_proxy(self):
        handler = self.handler()
        with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
            handler.do_POST()
        self.assertEqual(save.call_args.args[0]['RETROMODEM_PROXY_PAGE_SIZE'], '12000')
        self.assertNotIn('RETROMODEM_PROXY_PAGE_IMAGES', save.call_args.args[0])
        self.assertEqual(save.call_args.args[0]['RETROMODEM_PROXY_IMAGE_START'], 'inline')
        run.assert_not_called()
        self.assertEqual(handler.location, '/settings#webproxy')

    def test_invalid_inputs_never_save_or_restart(self):
        for size, images in [('99999', '5')]:
            handler = self.handler(size, images)
            with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
                handler.do_POST()
            self.assertEqual(handler.error, 400)
            save.assert_not_called()
            run.assert_not_called()

    def test_clear_start_modes_and_legacy_image_count_is_ignored(self):
        for start in ('inline', 'links', 'remember'):
            page = web.proxy_settings_card('nl', {'RETROMODEM_PROXY_IMAGE_START': start})
            self.assertIn(f'value="{start}" selected', page)
            self.assertIn('Afbeeldingen bij starten', page)
            self.assertNotIn('In de tekst tonen', page)
            handler = self.handler('100000', 'arbitrary legacy value')
            handler.form = lambda: dict(mode='manual', image_start=start, exceptions='example.org',
                                        image_width='144', image_height='120', page_size='100000')
            with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
                handler.do_POST()
            self.assertEqual(save.call_args.args[0]['RETROMODEM_PROXY_IMAGE_START'], start)
            self.assertNotIn('RETROMODEM_PROXY_PAGE_IMAGES', save.call_args.args[0])
            run.assert_not_called()

    def test_mode_change_applies_only_firewall(self):
        handler = self.handler()
        handler.config = lambda: {'RETROMODEM_PROXY_MODE': 'transparent'}
        with patch.object(web, 'save_config'), patch.object(web, 'run') as run:
            run.return_value.returncode = 0
            handler.do_POST()
        run.assert_called_once_with('/usr/local/lib/retromodem/proxy-firewall', 'apply')

    def test_invalid_start_mode_rejected_without_writes(self):
        handler = self.handler()
        handler.form = lambda: dict(mode='manual', image_start='invalid', page_size='100000')
        with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
            handler.do_POST()
        self.assertEqual(handler.error, 400)
        save.assert_not_called()
        run.assert_not_called()

    def test_mode_failure_restores_previous_mode_without_restart(self):
        handler = self.handler()
        handler.config = lambda: {'RETROMODEM_PROXY_MODE': 'transparent'}
        with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
            run.return_value.returncode = 1
            handler.do_POST()
        self.assertEqual(handler.error, 500)
        self.assertEqual(save.call_args.args[0], {'RETROMODEM_PROXY_MODE': 'transparent'})
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.args == ('/usr/local/lib/retromodem/proxy-firewall', 'apply') for call in run.call_args_list))
