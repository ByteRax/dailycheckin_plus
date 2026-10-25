import unittest
from unittest.mock import Mock

from dailycheckin.fnnasclub.main import FnNasClub


class FnNasClubParsingTests(unittest.TestCase):
    def test_extracts_sign_when_anchor_attributes_are_reordered(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            headers={},
            text=('<a class="btna" title="签到" href="plugin.php?id=zqlj_sign&sign=Ab12ef"> 点击打卡 </a>'),
        )

        self.assertEqual(FnNasClub.get_sign_param_from_page(session), "Ab12ef")

    def test_extracts_signed_state_when_anchor_contains_extra_markup(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            headers={},
            text=('<a href="plugin.php?id=zqlj_sign&sign=0123" class="btna"><span>今日已打卡</span></a>'),
        )

        self.assertEqual(FnNasClub.get_sign_param_from_page(session), "0123")

    def test_rejects_intercepted_page_instead_of_returning_empty_sign(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            headers={"X-Tengine-Error": "denied by http_custom"},
            text="",
        )

        with self.assertRaisesRegex(RuntimeError, "有效签到页面"):
            FnNasClub.get_sign_param_from_page(session)

    def test_extracts_checkin_info_from_flexible_section_markup(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            text=(
                '<div class="bm_c"><strong>我的打卡动态</strong>'
                "<ul><li>连续签到：12 天</li><li>今日奖励: 5 积分</li></ul></div>"
            ),
        )

        self.assertEqual(
            FnNasClub.get_info(session),
            [
                {"name": "连续签到", "value": "12 天"},
                {"name": "今日奖励", "value": "5 积分"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
