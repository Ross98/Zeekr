"""Sampling controls preserve unrelated fields under real process contention."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control import sampling
from zeekr_control.delivery_state import delivery_lock,DeliveryBusy


def paused_settings_writer(root,ready,release):
    original=sampling.read_settings
    def held_read(path):
        result=original(path);ready.set()
        if not release.wait(5):raise TimeoutError('test release not received')
        return result
    with patch.object(sampling,'read_settings',held_read):
        sampling.save_settings(root,False)


def exiting_settings_writer(root):
    import os
    with patch.object(sampling,'save',side_effect=lambda *args:os._exit(73)):
        sampling.save_settings(root,False)


class SamplingUpdateTests(unittest.TestCase):
    def test_failed_local_write_is_not_replayed_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sampling.save_settings(root,False,30)
            original=(root/'sampling.json').read_bytes()
            with patch.object(sampling,'save',side_effect=OSError('synthetic storage failure')) as write:
                with self.assertRaises(OSError):sampling.save_interval(root,60)
                write.assert_called_once()
            self.assertEqual((root/'sampling.json').read_bytes(),original)
            sampling.save_interval(root,60)
            self.assertEqual(sampling.read_settings(root),(False,60))

    def test_process_exit_releases_settings_lock_without_partial_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sampling.save_settings(root,True,30)
            original=(root/'sampling.json').read_bytes()
            worker=multiprocessing.get_context('spawn').Process(target=exiting_settings_writer,args=(root,))
            worker.start();worker.join(3)
            if worker.is_alive():worker.terminate();worker.join()
            self.assertEqual(worker.exitcode,73)
            self.assertEqual((root/'sampling.json').read_bytes(),original)
            sampling.save_interval(root,60)
            self.assertEqual(sampling.read_settings(root),(True,60))

    def test_read_modify_write_cannot_clobber_another_process_interval(self):
        for mode in ('settings','interval'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);sampling.save_settings(root,True,30)
                context=multiprocessing.get_context('spawn');ready=context.Event();release=context.Event()
                worker=context.Process(target=paused_settings_writer,args=(root,ready,release));worker.start()
                signals=queue.Queue();original_save=sampling.save
                @contextmanager
                def observed_lock(path):
                    try:
                        with delivery_lock(path):yield
                    except DeliveryBusy:signals.put('waiting');raise
                def observed_save(*args):
                    original_save(*args);signals.put('saved')
                try:
                    self.assertTrue(ready.wait(3),'first process never read settings')
                    with patch.object(sampling,'delivery_lock',observed_lock,create=True),\
                         patch.object(sampling,'save',observed_save),ThreadPoolExecutor(max_workers=1) as pool:
                        future=(pool.submit(sampling.save_settings,root,True,60) if mode=='settings'
                                else pool.submit(sampling.save_interval,root,60))
                        signals.get(timeout=2)  # Old code saves; corrected code observes the held file lock.
                        release.set();future.result(timeout=3)
                    worker.join(3)
                    self.assertEqual(worker.exitcode,0)
                    self.assertEqual(sampling.read_settings(root),(mode=='settings',60))
                finally:
                    release.set();worker.join(2)
                    if worker.is_alive():worker.terminate();worker.join()
