import unittest

from big_ambitions_drive_sync import merge_daily_csv_bytes


class MergeDailyCsvBytesTests(unittest.TestCase):
    def test_appends_only_new_rows(self):
        existing = b"Id,Day,Type,Amount\n1,12,Rent,-100\n2,12,Shop,50\n"
        new = b"Id,Day,Type,Amount\n2,12,Shop,50\n3,12,Cafe,-20\n"

        merged, appended_count = merge_daily_csv_bytes(existing, new)

        self.assertEqual(appended_count, 1)
        self.assertEqual(
            merged.decode("utf-8"),
            "Id,Day,Type,Amount\n1,12,Rent,-100\n2,12,Shop,50\n3,12,Cafe,-20\n",
        )

    def test_uses_existing_header_when_both_have_headers(self):
        existing = b"OldHeader,Day,Type,Amount\n1,1,A,10\n"
        new = b"NewHeader,Day,Type,Amount\n2,1,B,20\n"

        merged, _ = merge_daily_csv_bytes(existing, new)

        self.assertTrue(merged.decode("utf-8").startswith("OldHeader,Day,Type,Amount\n"))


if __name__ == "__main__":
    unittest.main()
