import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import voice_progress_worker as worker


class VoiceProgressWorkerTests(unittest.TestCase):
    def test_body_hold_prevents_render_and_play(self):
        verdict = {'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME'}
        def hold():
            raise worker.BodyHold(verdict)
        play = Mock()
        with patch.dict(sys.modules, {'speak': None}):
            response = worker.handle_request(
                {'text': 'progress'},
                render=lambda text: worker.render_and_play(text, authorize=hold, play=play))
        self.assertEqual(response, {'status': 'HOLD', 'verdict': verdict})
        play.assert_not_called()

    def test_stop_request_is_acknowledged(self):
        self.assertEqual(worker.handle_request({'command': 'stop'}), {'status': 'STOPPED'})

    def test_render_uses_drone_voice_and_memory_playback(self):
        fake_speak = ModuleType('speak')
        fake_speak.free_gpu = Mock()
        fake_speak.render_wav = Mock(return_value=b'pcm-wav')
        play = Mock()
        with patch.dict(sys.modules, {'speak': fake_speak}), \
                patch.object(worker, '_TORCH_CONFIGURED', True):
            result = worker.render_and_play(
                'bounded update', authorize=Mock(return_value={'allowed': True}),
                play=play, lock_factory=nullcontext)
        self.assertEqual(result, {'status': 'SPOKEN', 'mode': 'logic'})
        fake_speak.render_wav.assert_called_once_with('bounded update', 'logic')
        fake_speak.free_gpu.assert_not_called()
        play.assert_called_once_with(b'pcm-wav')

    def test_body_hold_after_render_prevents_audio_playback(self):
        verdict = {'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME'}
        fake_speak = ModuleType('speak')
        fake_speak.render_wav = Mock(return_value=b'pcm-wav')
        authorize = Mock(side_effect=[{'allowed': True}, {'allowed': True},
                                      worker.BodyHold(verdict)])
        play = Mock()
        with patch.dict(sys.modules, {'speak': fake_speak}), \
                patch.object(worker, '_TORCH_CONFIGURED', True):
            response = worker.handle_request(
                {'text': 'bounded update'},
                render=lambda text: worker.render_and_play(
                    text, authorize=authorize, play=play, lock_factory=nullcontext))
        self.assertEqual(response, {'status': 'HOLD', 'verdict': verdict})
        self.assertEqual(authorize.call_count, 3)
        fake_speak.render_wav.assert_called_once_with('bounded update', 'logic')
        play.assert_not_called()


if __name__ == '__main__':
    unittest.main()
