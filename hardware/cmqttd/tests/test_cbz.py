from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from cbus.toolkit.cbz import CBZ


def test_cbz_uses_the_only_xml_member_when_archive_has_other_files():
    source = Path(__file__).parent / 'data' / 'example-demo.cbz'
    with ZipFile(source, 'r') as source_zip:
        xml_name = source_zip.namelist()[0]
        xml_data = source_zip.read(xml_name)

    archive = BytesIO()
    with ZipFile(archive, 'w', ZIP_DEFLATED) as output:
        output.writestr('metadata.json', b'{}')
        output.writestr('README.txt', b'archive metadata')
        output.writestr(xml_name, xml_data)

    installation = CBZ(BytesIO(archive.getvalue())).installation
    assert installation.project is not None
