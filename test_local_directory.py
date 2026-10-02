import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import local_directory
import server
from starlette.requests import Request


def request(host='127.0.0.1', origin='http://127.0.0.1:8770'):
    return Request({'type':'http','method':'POST','scheme':'http','path':'/api/local-directory',
                    'query_string':b'','server':('127.0.0.1',8770),'client':(host,1234),
                    'headers':[(b'host',b'127.0.0.1:8770')]+([(b'origin',origin.encode())] if origin else [])})


class DirectoryPickerContracts(unittest.TestCase):
    def test_folder_round_trip_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            result=SimpleNamespace(returncode=0,stdout=json.dumps({'path':folder}))
            with patch('local_directory.subprocess.run',return_value=result) as run:
                self.assertEqual(local_directory.choose_directory(),str(Path(folder).resolve()))
                self.assertNotIn('shell',run.call_args.kwargs)
        with patch('local_directory.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"path":null}')):
            self.assertIsNone(local_directory.choose_directory())

    def test_missing_folder_and_failed_dialog(self):
        with patch('local_directory.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"path":"missing-relative-folder"}')):
            with self.assertRaises(RuntimeError):local_directory.choose_directory()
        with patch('local_directory.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='')):
            with self.assertRaises(RuntimeError):local_directory.choose_directory()

    def test_endpoint_round_trip_and_cancel(self):
        for selected in (None,str(Path.cwd())):
            with patch('server.choose_directory',return_value=selected):
                self.assertEqual(server.local_directory(request(),server.DirectorySelection()),{'path':selected})

    def test_no_remote_or_cross_site_desktop_dialog(self):
        for req in (request('192.168.1.2'),request(origin='https://example.com'),request(origin='')):
            with patch('server.choose_directory') as dialog:
                with self.assertRaises(server.HTTPException) as error:server.local_directory(req,server.DirectorySelection())
                self.assertEqual(error.exception.status_code,403);dialog.assert_not_called()


if __name__=='__main__':unittest.main()
