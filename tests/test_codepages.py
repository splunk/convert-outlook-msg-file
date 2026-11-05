import io
import struct
import unittest

import outlookmsgfile as parser


class Container(dict):
    def __iter__(self):
        # These fixtures contain properties only, with no attachment entries.
        return iter(())


class Document:
    def __init__(self):
        self.streams = {}

    def open(self, name):
        return io.BytesIO(self.streams[name])


def property_container(doc, name, entries, top_level=True):
    container = Container()
    data = bytearray(32 if top_level else 24)
    for tag, kind, value in entries:
        if kind == 3:
            inline = struct.pack('<I', value) + b'\0' * 4
        elif kind == 13:
            container['__substg1.0_{:04X}{:04X}'.format(tag, kind)] = value
            inline = b'\0' * 8
        else:
            key = '__substg1.0_{:04X}{:04X}'.format(tag, kind)
            container[key] = name + '/' + key
            doc.streams[container[key]] = value
            inline = struct.pack('<I', len(value)) + b'\0' * 4
        data.extend(struct.pack('<HHI8s', kind, tag, 0, inline))
    container['__properties_version1.0'] = name + '/properties'
    doc.streams[container['__properties_version1.0']] = bytes(data)
    return container


def read_properties(entries):
    doc = Document()
    container = property_container(doc, 'root', entries)
    return parser.parse_properties(container['__properties_version1.0'], True, container, doc)


class CodepageTests(unittest.TestCase):
    def test_metadata_order_does_not_change_decoding(self):
        subject = (0x0037, 30, 'Привет'.encode('cp1251'))
        codepage = (0x3FFD, 3, 1251)
        for entries in ([subject, codepage], [codepage, subject]):
            with self.subTest(entries=entries):
                self.assertEqual(read_properties(entries)['SUBJECT'], 'Привет')

    def test_body_and_subject_prefer_their_own_codepages(self):
        result = read_properties([
            (0x1000, 30, 'Привет'.encode('cp1251')),
            (0x0037, 30, 'γειά'.encode('cp1253')),
            (0x3FDE, 3, 1251),
            (0x3FFD, 3, 1253),
        ])
        self.assertEqual(result['BODY'], 'Привет')
        self.assertEqual(result['SUBJECT'], 'γειά')

    def test_alternate_codepage_used_if_preferred_cannot_decode(self):
        result = read_properties([
            (0x0037, 30, b'\x81'),
            (0x3FFD, 3, 1252),
            (0x3FDE, 3, 1251),
        ])
        self.assertEqual(result['SUBJECT'], b'\x81'.decode('cp1251'))

    def test_body_codepage_alone_can_decode_other_properties(self):
        result = read_properties([(0x0037, 30, 'Привет'.encode('cp1251')), (0x3FDE, 3, 1251)])
        self.assertEqual(result['SUBJECT'], 'Привет')

    def test_missing_metadata_keeps_utf8_fallback(self):
        self.assertEqual(read_properties([(0x0037, 30, 'Résumé ☃'.encode('utf8'))])['SUBJECT'], 'Résumé ☃')

    def test_missing_metadata_keeps_cp1252_fallback(self):
        self.assertEqual(read_properties([(0x0037, 30, 'Résumé'.encode('cp1252'))])['SUBJECT'], 'Résumé')

    def test_unknown_metadata_keeps_utf8_fallback(self):
        result = read_properties([(0x0037, 30, '日本語'.encode('utf8')), (0x3FFD, 3, 99999)])
        self.assertEqual(result['SUBJECT'], '日本語')

    def test_incorrect_ascii_metadata_keeps_utf8_fallback(self):
        result = read_properties([(0x0037, 30, 'Résumé ☃'.encode('utf8')), (0x3FFD, 3, 20127)])
        self.assertEqual(result['SUBJECT'], 'Résumé ☃')

    def test_multibyte_codepage(self):
        result = read_properties([(0x0037, 30, '日本語 →'.encode('cp932')), (0x3FFD, 3, 932)])
        self.assertEqual(result['SUBJECT'], '日本語 →')

    def test_gbk_extension(self):
        result = read_properties([(0x0037, 30, '镕'.encode('gbk')), (0x3FFD, 3, 936)])
        self.assertEqual(result['SUBJECT'], '镕')

    def test_iso_codepage(self):
        result = read_properties([(0x0037, 30, 'κόσμος'.encode('iso8859_7')), (0x3FFD, 3, 28597)])
        self.assertEqual(result['SUBJECT'], 'κόσμος')

    def test_existing_utf16_surrogate_behavior_is_preserved(self):
        result = read_properties([(0x0037, 31, b'\x00\xd8'), (0x3FFD, 3, 1251)])
        self.assertEqual(result['SUBJECT'], '\ud800')

    def test_binary_values_unchanged(self):
        value = b'\xff\x81\x00'
        result = read_properties([(0x1009, 258, value), (0x3FFD, 3, 1251)])
        self.assertEqual(result['RTF_COMPRESSED'], value)

    def test_string8_public_default_and_nul_behavior_unchanged(self):
        self.assertEqual(parser.STRING8.load('Résumé ☃'.encode('utf8')), 'Résumé ☃')
        self.assertEqual(parser.STRING8.load(b'hello\0'), 'hello\0')
        with self.assertRaises(UnicodeDecodeError):
            parser.STRING8.load(b'\x81')

    def test_embedded_message_uses_its_own_metadata(self):
        doc = Document()
        nested = property_container(doc, 'nested', [
            (0x0037, 30, 'γειά'.encode('cp1253')),
            (0x3FFD, 3, 1253),
        ], top_level=False)
        root = property_container(doc, 'root', [
            (0x0037, 30, 'Привет'.encode('cp1251')),
            (0x3FFD, 3, 1251),
            (0x3701, 13, nested),
        ])
        result = parser.parse_properties(root['__properties_version1.0'], True, root, doc)
        self.assertEqual(result['SUBJECT'], 'Привет')
        self.assertEqual(str(result['ATTACH_DATA_BIN']['Subject']), 'γειά')

    def test_last_property_value_wins_across_string_types(self):
        result = read_properties([
            (0x0037, 30, b'old'),
            (0x0037, 31, 'new'.encode('utf16')),
            (0x3FFD, 3, 1251),
        ])
        self.assertEqual(result['SUBJECT'], 'new')


if __name__ == '__main__':
    unittest.main()
