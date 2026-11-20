import unittest
import xml.etree.ElementTree as ET
from hoverling.formatting import render_markdown


class FormattingTests(unittest.TestCase):
    def render(self,text):
        result=render_markdown(text)
        parsed=ET.fromstring('<markup>'+result.markup+'</markup>')
        self.assertEqual(''.join(parsed.itertext()),result.text)
        return result

    def test_screenshot_bold_labels_with_spaces_and_list_terms(self):
        result=self.render('**译文： ** 这些技能随安装附带。\n\n**解析： **\n- **ship**：此处意为随附提供。\n- **install**：一次安装。')
        self.assertIn('<b>译文：</b>',result.markup)
        self.assertIn('<b>ship</b>',result.markup)
        self.assertIn('• ship：此处意为随附提供。',result.text)
        self.assertNotIn('**',result.text)

    def test_headings_lists_and_italic(self):
        result=self.render('## 解释\n- **短语**与 *含义*\n1. 示例')
        self.assertEqual(result.text,'解释\n• 短语与 含义\n1. 示例')
        self.assertIn('<i>含义</i>',result.markup)

    def test_inline_code_keeps_literal_stars(self):
        result=self.render('参数 `**kwargs` 和 `<tag>&`。')
        self.assertEqual(result.text,'参数 **kwargs 和 <tag>&。')
        self.assertIn('<tt>**kwargs</tt>',result.markup)

    def test_code_block_is_not_reinterpreted_as_emphasis(self):
        result=self.render('```python\n**literal** <value>\n```')
        self.assertEqual(result.text,'**literal** <value>')
        self.assertIn('<tt>',result.markup)

    def test_literal_html_and_entities_are_escaped(self):
        text='<span size="999999">A & B</span><img src="x">'
        result=self.render(text)
        self.assertEqual(result.text,text)
        self.assertNotIn('<span',result.markup)
        self.assertNotIn('<img',result.markup)

    def test_links_are_readable_and_not_active_markup(self):
        result=self.render('[官网](https://example.com?a=1&b=2)')
        self.assertEqual(result.text,'官网 (https://example.com?a=1&b=2)')
        self.assertNotIn('<a ',result.markup)

    def test_math_and_word_underscores_remain_literal(self):
        text='2 * 3 * 4; 2*3*4; workflow_name'
        self.assertEqual(self.render(text).text,text)

    def test_backslash_escaped_stars_remain_literal(self):
        result=self.render(r'\*literal\*')
        self.assertEqual(result.text,'*literal*')
        self.assertNotIn('<i>',result.markup)

    def test_unclosed_markers_remain_valid_text(self):
        text='未结束的 **标题 & <内容>'
        self.assertEqual(self.render(text).text,text)

    def test_large_response_is_preserved_without_truncation(self):
        text='**文字 & <tag>**'*5000
        result=self.render(text)
        self.assertEqual(result.text,text)


if __name__=='__main__':unittest.main()
