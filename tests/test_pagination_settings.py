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
            self.assertIn('name="page_images" min="1" max="10" value="5"', page)
            page = web.proxy_settings_card(language, {'RETROMODEM_PROXY_PAGE_SIZE': '0', 'RETROMODEM_PROXY_PAGE_IMAGES': '2'})
            self.assertIn('value="0" selected', page)
            self.assertIn('max="10" value="2"', page)

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

    def test_save_persists_both_options_and_restarts_proxy(self):
        handler = self.handler()
        with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
            handler.do_POST()
        self.assertEqual(save.call_args.args[0]['RETROMODEM_PROXY_PAGE_SIZE'], '12000')
        self.assertEqual(save.call_args.args[0]['RETROMODEM_PROXY_PAGE_IMAGES'], '2')
        self.assertIn('retromodem-proxy.service', run.call_args.args)
        self.assertEqual(handler.location, '/settings#webproxy')

    def test_invalid_inputs_never_save_or_restart(self):
        for size, images in [('99999', '5'), ('18000', '0'), ('0', '11'), ('12000', '<script>')]:
            handler = self.handler(size, images)
            with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
                handler.do_POST()
            self.assertEqual(handler.error, 400)
            save.assert_not_called()
            run.assert_not_called()
