"""Behavior checks using temporary files; never mounts USB or opens a real camera."""
import json
import os
from pathlib import Path
import pty
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import numpy as np

# Set before importing the application: test logs/data must not touch user recordings.
_test_data=tempfile.TemporaryDirectory(prefix='dvp-tests-')
os.environ['DVP_DATA_DIR']=_test_data.name
from app import config
from app.state import state,State
from ai.inference import InferenceEngine,decode
from ai.detection import DetectionWorker
from ai.motion import MotionDetector
from hardware.buzzer import Buzzer
from hardware.camera import CameraManager,FramePacket
from hardware.display import DisplayOutput,parse_xrandr_size
from hardware.ina226 import (INA226Monitor,battery_bars,REG_BUS_VOLTAGE,
                             REG_SHUNT_VOLTAGE,REG_COMPAT_CURRENT,REG_CURRENT,
                             REG_CALIBRATION,REG_MANUFACTURER_ID,REG_DIE_ID)
from hardware.touch_bridge import parse_message,TouchBridge
from hardware.usb import copy_snapshot,discover_drives,USBMonitor,Drive
from hardware.zoom import make_view,map_boxes
from recording.mission import MissionManager
from recording.recorder import Timeline,VideoRecorder
from ui.touch import TouchHandler
from ui.ui import DVPUI,GREEN,YELLOW,RED

def wait_for(predicate,seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Timed out waiting for background work')

class Base(unittest.TestCase):
    def setUp(self):
        state.__dict__.update(State().__dict__)
        self.tmp=tempfile.TemporaryDirectory(prefix='dvp-case-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

class BuzzerTests(Base):
    def test_started_success_failure_and_silence_patterns(self):
        gpio=Mock()
        gpio.gpiochip_open.return_value=7
        buzzer=Buzzer(enabled=True,gpio_module=gpio,beep_seconds=.01,
                      success_gap_seconds=.005,success_repeat_seconds=.08,
                      failure_seconds=.03)
        self.addCleanup(buzzer.stop)
        buzzer.start()

        buzzer.export_started()
        wait_for(lambda: gpio.tx_pwm.call_count>=1)
        wait_for(lambda: gpio.tx_pulse.call_count>=1)

        before=gpio.tx_pwm.call_count
        buzzer.export_succeeded()
        wait_for(lambda: gpio.tx_pwm.call_count>=before+3)

        buzzer.silence()
        wait_for(lambda: gpio.gpio_write.call_count>=1)
        before=gpio.tx_pwm.call_count
        buzzer.export_failed()
        wait_for(lambda: gpio.tx_pwm.call_count>=before+1)
        wait_for(lambda: buzzer.mode==Buzzer.SILENT)
        self.assertTrue(buzzer.stop())
        gpio.gpiochip_close.assert_called_once_with(7)

class DetectionTests(Base):
    def test_supplied_model_runs_without_pytorch(self):
        engine=InferenceEngine()
        self.assertEqual((engine.h,engine.w),(320,320))
        boxes,elapsed=engine.infer(np.zeros((720,1280,3),np.uint8))
        self.assertEqual(boxes,[])
        self.assertGreater(elapsed,0)

    def test_person_filter_letterbox_and_nms(self):
        anchors=np.zeros((1,84,3),np.float32)
        anchors[0,:4,0]=(160,160,80,80)
        anchors[0,4,0]=.9
        anchors[0,:4,1]=(161,161,80,80)
        anchors[0,4,1]=.8
        anchors[0,:4,2]=(50,100,20,20)
        anchors[0,4,2]=.8
        anchors[0,6,2]=.95  # another class wins; do not mark it as a person
        boxes=decode(anchors,(720,1280),(.25,.25,0,70))
        self.assertEqual(len(boxes),1)
        np.testing.assert_allclose(boxes[0]['box'],(480,200,800,520))

    def test_detection_expiry_generation_and_clear(self):
        worker=DetectionWorker()
        box=[{'box':(1,2,3,4),'confidence':.9}]
        worker.result=(time.monotonic(),1,box)
        self.assertEqual(worker.latest(1),box)
        self.assertEqual(worker.latest(2),[])
        worker.result=(time.monotonic()-2,1,box)
        self.assertEqual(worker.latest(1),[])
        worker.clear()
        self.assertEqual(worker.latest(1),[])

    def test_missing_model_disables_detection_without_raising(self):
        with patch('ai.detection.InferenceEngine',side_effect=RuntimeError('missing model')):
            worker=DetectionWorker()
            worker.start()
            worker.thread.join(2)
            self.assertFalse(worker.thread.is_alive())
            self.assertEqual(state.ai_status,'UNAVAILABLE')

    def test_motion_and_global_change_suppression(self):
        detector=MotionDetector()
        black=np.zeros((180,320,3),np.uint8)
        moving=black.copy()
        moving[60:90,60:90]=255
        detector.detect(black)
        detector.detect(moving)
        self.assertTrue(state.motion_detected)
        detector.detect(np.full_like(black,255))
        self.assertTrue(state.scene_moving)
        self.assertFalse(state.motion_detected)

    def test_zoom_does_not_change_raw_frame(self):
        raw=np.zeros((720,1280,3),np.uint8)
        state.zoom=2
        view,transform=make_view(raw)
        DVPUI().draw(view)
        self.assertFalse(raw.any())
        boxes=map_boxes([{'box':(0,0,1280,720),'confidence':.9}],transform)
        self.assertEqual(boxes[0]['box'],(0,15,800,465))

class RecordingTests(Base):
    def test_closed_recorder_allows_shutdown_after_prior_low_space_error(self):
        recorder=VideoRecorder(MissionManager(self.root/'missions'))
        state.record_error='Recording paused: insufficient free space'
        recorder.start()
        self.assertTrue(recorder.stop())

    def test_timeline_keeps_elapsed_time_with_missing_frames(self):
        written=[]
        timeline=Timeline(30,written.append)
        for stamp,frame in ((0,'a'),(.033,'b'),(.1,'c'),(.1001,'d')):
            timeline.push(stamp,frame)
        self.assertEqual(written,['a','b','b','c'])
        self.assertEqual(timeline.duplicates,1)
        self.assertEqual(timeline.skipped,1)

    def test_queue_is_bounded_and_retains_close_boundary(self):
        recorder=VideoRecorder(MissionManager(self.root/'missions'))
        with patch.object(config,'RECORD_QUEUE_FRAMES',2):
            recorder.submit(np.zeros((2,2,3),np.uint8),1,'raw')
            recorder.boundary()
            recorder.submit(np.zeros((2,2,3),np.uint8),2,'raw')
            recorder.submit(np.zeros((2,2,3),np.uint8),3,'raw')
        self.assertEqual([x[0] for x in recorder.queue],['close','frame','frame'])
        self.assertEqual(state.record_dropped,1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_real_encoder_duration_at_fifteen_input_fps(self):
        missions=MissionManager(self.root/'missions')
        recorder=VideoRecorder(missions)
        with patch.object(config,'RECORD_QUEUE_FRAMES',64):
            recorder.start()
            try:
                start=time.monotonic()
                for i in range(30):
                    frame=np.full((240,320,3),i*5,np.uint8)
                    recorder.submit(frame,start+i/15,'raw')
                folder=recorder.boundary(wait=True)
            finally:
                clean=recorder.stop()
        self.assertTrue(clean)
        meta=json.loads((folder/'mission.json').read_text())
        self.assertEqual(meta['status'],'finished')
        segment=meta['segments'][0]
        self.assertEqual(segment['frames'],59)
        self.assertEqual(segment['duplicated_frames'],29)
        video=folder/segment['file']
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
            'format=duration:stream=width,height','-of','json',str(video)],text=True))
        self.assertAlmostEqual(float(probe['format']['duration']),59/30,delta=.04)
        self.assertEqual(probe['streams'][0]['width'],320)
        self.assertFalse(list(folder.glob('*.partial.mp4')))

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_large_camera_gap_starts_new_mission(self):
        missions=MissionManager(self.root/'missions')
        recorder=VideoRecorder(missions)
        recorder.start()
        try:
            now=time.monotonic()
            frame=np.zeros((120,160,3),np.uint8)
            recorder.submit(frame,now,'raw')
            recorder.submit(frame,now+3,'raw')
            recorder.boundary(wait=True)
        finally:
            recorder.stop()
        self.assertEqual(len(missions.completed()),2)
        for folder in missions.completed():
            meta=json.loads((folder/'mission.json').read_text())
            self.assertEqual(meta['segments'][0]['duplicated_frames'],0)

class ExportTests(Base):
    def mission(self,manager):
        folder=manager.start('raw')
        (folder/'video.mp4').write_bytes(b'video contents')
        manager.add_segment({'file':'video.mp4'})
        manager.finish()
        return folder

    def test_verified_export_preserves_existing_files_and_excludes_partial(self):
        manager=MissionManager(self.root/'missions')
        source=self.mission(manager)
        (source/'unfinished.partial.mp4').write_bytes(b'partial')
        mount=self.root/'usb'
        mount.mkdir()
        sentinel=mount/'user-file.txt'
        sentinel.write_text('keep')
        first=copy_snapshot([source],mount)
        second=copy_snapshot([source],mount)
        self.assertNotEqual(first,second)
        self.assertEqual(sentinel.read_text(),'keep')
        self.assertEqual((first/source.name/'video.mp4').read_bytes(),b'video contents')
        self.assertFalse((first/source.name/'unfinished.partial.mp4').exists())
        manifest=json.loads((first/'export_manifest.json').read_text())
        self.assertTrue(manifest['verified'])
        self.assertEqual(len(manifest['files']),2)
        self.assertTrue(all(len(x['sha256'])==64 for x in manifest['files']))
        self.assertTrue((first/'EXPORT_COMPLETE.txt').is_file())

    def test_cancel_and_removed_drive_never_report_complete_export(self):
        manager=MissionManager(self.root/'missions')
        source=self.mission(manager)
        mount=self.root/'usb'
        mount.mkdir()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            copy_snapshot([source],mount,cancel=lambda:True)
        self.assertEqual(list(mount.glob('DVP_Export_*')),[])
        with self.assertRaisesRegex(RuntimeError,'removed'):
            copy_snapshot([source],mount,validate=Mock(side_effect=RuntimeError('removed')))
        self.assertEqual(list(mount.glob('DVP_Export_*')),[])

    def test_no_space_and_symlink_refused(self):
        manager=MissionManager(self.root/'missions')
        source=self.mission(manager)
        mount=self.root/'usb'
        mount.mkdir()
        with patch('hardware.usb.shutil.disk_usage',return_value=Mock(free=0)):
            with self.assertRaisesRegex(RuntimeError,'insufficient'):
                copy_snapshot([source],mount)
        (source/'linked').symlink_to(self.root/'outside')
        with self.assertRaisesRegex(RuntimeError,'symlink'):
            copy_snapshot([source],mount)

    def test_checksum_failure_retains_only_a_partial_export(self):
        import builtins
        import io
        manager=MissionManager(self.root/'missions')
        source=self.mission(manager)
        mount=self.root/'usb'
        mount.mkdir()
        real_open=builtins.open
        def corrupted_read(path,mode='r',*args,**kwargs):
            if mode=='rb' and '.DVP_Export_' in str(path) and str(path).endswith('video.mp4'):
                return io.BytesIO(b'corrupted copy')
            return real_open(path,mode,*args,**kwargs)
        with patch('builtins.open',side_effect=corrupted_read):
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                copy_snapshot([source],mount)
        self.assertEqual(list(mount.glob('DVP_Export_*')),[])
        self.assertEqual(len(list(mount.glob('.*.partial'))),1)

    def test_active_and_exporting_missions_protected_from_deletion(self):
        manager=MissionManager(self.root/'missions')
        completed=self.mission(manager)
        pins=manager.pin_completed()
        active=manager.start('raw')
        self.assertIsNone(manager.delete_oldest())
        manager.unpin(pins)
        self.assertEqual(manager.delete_oldest(),completed.name)
        self.assertTrue(active.exists())
        self.assertIsNone(manager.delete_oldest())

    def test_selected_recordings_delete_only_exact_unprotected_sessions(self):
        manager=MissionManager(self.root/'missions')
        first=self.mission(manager)
        second=self.mission(manager)
        third=self.mission(manager)
        manager.pinned.add(second)
        deleted=manager.delete_selected([first.name,second.name,'Mission_9999'])
        self.assertEqual(deleted,[first.name])
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue(third.exists())
        info=manager.completed_info()
        self.assertEqual([item['name'] for item in info],[third.name,second.name])
        self.assertTrue(next(item for item in info if item['name']==second.name)['protected'])

    def test_export_pins_before_recorder_finishes(self):
        manager=MissionManager(self.root/'missions')
        source=manager.start('raw')
        (source/'video.mp4').write_bytes(b'video')
        manager.add_segment({'file':'video.mp4'})
        def close(wait):
            self.assertIn(source,manager.pinned)
            manager.finish()
            self.assertIsNone(manager.delete_oldest())
        recorder=Mock()
        recorder.boundary.side_effect=close
        buzzer=Mock()
        monitor=USBMonitor(manager,recorder,buzzer)
        mount=self.root/'usb'
        mount.mkdir()
        monitor.drive=Drive('/dev/sdb1','test','test',str(mount),'/dev/sdb')
        with patch('hardware.usb.os.path.ismount',return_value=True):
            monitor._export(latest=True)
        buzzer.export_started.assert_called_once_with()
        self.assertFalse(state.export_busy)
        self.assertEqual(manager.pinned,set())
        self.assertEqual(len(list(mount.glob('DVP_Export_*'))),1)

    def test_missing_mount_clears_export_busy(self):
        monitor=USBMonitor(MissionManager(self.root/'missions'),Mock())
        monitor.drive=Drive('/dev/sdb1','test','test',str(self.root/'absent'),'/dev/sdb')
        with self.assertRaises(OSError):
            monitor._export(True)
        self.assertFalse(state.export_busy)

    def test_usb_boot_disk_and_data_disk_are_excluded(self):
        tree={'blockdevices':[
            {'name':'/dev/sda','tran':'usb','children':[
                {'name':'/dev/sda1','fstype':'vfat','mountpoints':['/boot/firmware']},
                {'name':'/dev/sda2','fstype':'ext4','mountpoints':['/']}]},
            {'name':'/dev/sdb','tran':'usb','children':[
                {'name':'/dev/sdb1','fstype':'exfat','mountpoints':['/media/export']}]},
            {'name':'/dev/sdc','tran':'usb','children':[
                {'name':'/dev/sdc1','fstype':'ext4','mountpoints':['/mnt/data']}]},
            {'name':'/dev/mmcblk0','tran':None,'fstype':'ext4','mountpoints':['/mnt/internal']}]}
        drives=discover_drives(tree,('/mnt/data/recordings',))
        self.assertEqual([x.device for x in drives],['/dev/sdb1'])

    def test_new_usb_requests_all_recordings_and_clears_old_result(self):
        monitor=USBMonitor(MissionManager(self.root/'missions'),Mock())
        state.usb_export_error=True
        state.usb_last_result='failed'
        tree={'blockdevices':[{'name':'/dev/sdb','tran':'usb','children':[
            {'name':'/dev/sdb1','fstype':'exfat','uuid':'abc','label':'EXPORT',
             'mountpoints':['/media/export']}]}]}
        with patch('hardware.usb.run_command',return_value=json.dumps(tree)), \
             patch('hardware.usb.os.path.ismount',return_value=True), \
             patch.object(monitor,'request') as request:
            monitor.scan()
        request.assert_called_once_with('all')
        self.assertFalse(state.usb_export_error)
        self.assertEqual(state.usb_last_result,'')

    def test_safe_remove_result_survives_physical_removal(self):
        buzzer=Mock()
        monitor=USBMonitor(MissionManager(self.root/'missions'),Mock(),buzzer)
        monitor.ejected_disk='/dev/sdb'
        monitor._safe_to_remove(export_complete=True)
        buzzer.export_succeeded.assert_called_once_with()
        self.assertTrue(state.usb_safe_to_remove)
        self.assertFalse(state.usb_export_error)
        self.assertEqual(state.usb_last_result,'complete')
        inserted={'blockdevices':[{'name':'/dev/sdb','tran':'usb','children':[
            {'name':'/dev/sdb1','fstype':'exfat','uuid':'abc','mountpoints':[None]}]}]}
        with patch('hardware.usb.run_command',return_value=json.dumps(inserted)):
            monitor.scan()
        self.assertTrue(state.usb_safe_to_remove)
        with patch('hardware.usb.run_command',return_value=json.dumps({'blockdevices':[]})):
            monitor.scan()
        buzzer.silence.assert_called()
        self.assertFalse(state.usb_safe_to_remove)
        self.assertEqual(state.usb_last_result,'complete')


class DisplayAndBatteryTests(Base):
    def test_active_hdmi_mode_parsing(self):
        wireless='''Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
HDMI-1 connected primary 1920x1080+0+0
   1920x1080     60.00*+  59.94
   800x480       60.00
'''
        wired='''Screen 0: minimum 320 x 200, current 800 x 480, maximum 16384 x 16384
HDMI-1 connected 800x480+0+0
   800x480       59.99*+
'''
        self.assertEqual(parse_xrandr_size(wireless),(1920,1080))
        self.assertEqual(parse_xrandr_size(wired),(800,480))
        self.assertIsNone(parse_xrandr_size('no active output'))

    def test_local_touch_is_mapped_back_to_logical_canvas(self):
        handler=TouchHandler(DVPUI(),Mock())
        handler.set_output_size(1920,1080)
        x,y=handler.local_to_logical(960,540)
        self.assertAlmostEqual(x,400)
        self.assertAlmostEqual(y,240)

    def test_logical_canvas_fills_wireless_hdmi_mode(self):
        output=DisplayOutput((800,480),detect=True)
        with patch('hardware.display.detect_output_size',return_value=(1920,1080)):
            self.assertTrue(output.refresh(force=True))
        scaled=output.scale(np.zeros((480,800,3),np.uint8))
        self.assertEqual(scaled.shape,(1080,1920,3))

    def test_wireless_scaling_fills_every_output_pixel_without_borders(self):
        output=DisplayOutput((800,480),detect=True)
        output.size=(1920,1080)
        frame=np.empty((480,800,3),np.uint8)
        frame[:]=(17,83,201)
        scaled=output.scale(frame)
        self.assertEqual(scaled.shape,(1080,1920,3))
        self.assertTrue(np.all(scaled==(17,83,201)))

    def test_r005_ina226_conversion_calibration_and_four_bar_thresholds(self):
        class FakeBus:
            def __init__(self):
                self.writes=[]
                bus_raw=round(7.4/0.00125)
                shunt_raw=round((5.0*0.005)/2.5e-6)
                current_raw=round(5.0/config.INA226_CURRENT_LSB_A)
                swap=INA226Monitor._swap_word
                self.values={REG_MANUFACTURER_ID:swap(0x5449),
                             REG_DIE_ID:swap(0x2260),
                             REG_BUS_VOLTAGE:swap(bus_raw),
                             REG_SHUNT_VOLTAGE:swap(shunt_raw),
                             REG_CURRENT:swap(current_raw)}
            def write_word_data(self,address,register,value):
                self.writes.append((address,register,value))
            def read_word_data(self,address,register):
                return self.values[register]
            def close(self):
                pass
        bus=FakeBus()
        monitor=INA226Monitor(bus=bus)
        sample=monitor.read()
        self.assertIsNotNone(sample)
        self.assertAlmostEqual(sample.voltage,7.4,places=2)
        self.assertAlmostEqual(sample.current,5.0,places=2)
        self.assertAlmostEqual(sample.power,37.0,places=2)
        self.assertEqual(sample.bars,3)
        calibration_writes=[w for w in bus.writes if w[1]==REG_CALIBRATION]
        self.assertEqual(len(calibration_writes),1)
        self.assertEqual(INA226Monitor._swap_word(calibration_writes[0][2]),2048)
        self.assertEqual([battery_bars(v) for v in (6.4,6.5,7.0,7.4,7.8)],
                         [0,1,2,3,4])

    def test_installed_0x50_compatible_monitor_is_auto_detected(self):
        class FakeBus:
            def __init__(self):
                self.writes=[]
                swap=INA226Monitor._swap_word
                self.values={REG_MANUFACTURER_ID:swap(0x5449),
                             REG_DIE_ID:swap(0x2270),
                             REG_COMPAT_CURRENT:swap(0x06d5),
                             REG_BUS_VOLTAGE:swap(0x184f)}
            def write_word_data(self,address,register,value):
                self.writes.append((address,register,value))
            def read_word_data(self,address,register):
                if address != 0x50:
                    raise OSError(121,'Remote I/O error')
                return self.values[register]
            def close(self):
                pass
        bus=FakeBus()
        monitor=INA226Monitor(bus=bus)
        sample=monitor.read()
        self.assertIsNotNone(sample)
        self.assertEqual(monitor.address,0x50)
        self.assertEqual(monitor.variant,'compat2270')
        self.assertAlmostEqual(sample.voltage,7.77875,places=5)
        self.assertAlmostEqual(sample.current,2.18625,places=5)
        self.assertAlmostEqual(sample.power,17.006,places=3)
        self.assertEqual(sample.bars,4)
        self.assertEqual(bus.writes,[])

    def test_customer_power_dialog_contains_no_board_name(self):
        state.dialog='power'
        ui=DVPUI()
        rendered=[]
        ui.text=lambda img,text,*args,**kwargs: rendered.append(str(text))
        ui.draw(np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),np.uint8))
        visible=' '.join(rendered).upper()
        self.assertIn('DVP',visible)
        self.assertNotIn('PI 5',visible)
        self.assertNotIn('RASPBERRY',visible)

    def test_normal_overlay_omits_diagnostic_text(self):
        state.camera_connected=True
        state.battery_available=True
        state.battery_bars=3
        state.touch_status='OK'
        ui=DVPUI()
        rendered=[]
        ui.text=lambda img,text,*args,**kwargs: rendered.append(str(text))
        ui.draw(np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),np.uint8))
        visible=' '.join(rendered).upper()
        self.assertIn('TOUCH READY',visible)
        for forbidden in ('DROP','DUP','AI ','USB CAM',' GB','39C'):
            self.assertNotIn(forbidden,visible)

    def test_usb_control_is_not_present_on_operator_overlay(self):
        state.dialog=''
        state.ui_visible=True
        regions=DVPUI().rects()
        self.assertNotIn('USB',regions)
        self.assertIn('STORAGE',regions)

    def test_touch_link_states_are_operator_visible(self):
        ui=DVPUI()
        expected={
            'OK':('TOUCH READY',GREEN),
            'WAIT':('TOUCH SEARCHING',YELLOW),
            'LOST':('TOUCH LOST',RED),
            'PORT ERR':('TOUCH ERROR',RED),
        }
        for status,(message,colour) in expected.items():
            with self.subTest(status=status):
                state.status_until=0
                state.usb_last_result=''
                state.usb_export_error=False
                state.usb_safe_to_remove=False
                state.touch_status=status
                rendered=[]
                rectangles=[]
                ui.text=lambda img,text,*args,**kwargs: rendered.append(str(text))
                with patch('ui.ui.cv2.rectangle',side_effect=lambda img,a,b,c,t: rectangles.append(c)):
                    ui.touch_badge(np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),np.uint8))
                self.assertIn(message,rendered)
                self.assertIn(colour,rectangles)

    def test_temporary_message_does_not_hide_touch_link_state(self):
        state.touch_status='OK'
        state.status='RECORDING MODE - WITH UI'
        state.status_until=time.monotonic()+5
        ui=DVPUI()
        rendered=[]
        ui.text=lambda img,text,*args,**kwargs: rendered.append(str(text))
        ui.draw(np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),np.uint8))
        self.assertIn('RECORDING MODE - WITH UI',rendered)
        self.assertIn('TOUCH READY',rendered)

    def test_top_status_and_recording_mode_are_visible(self):
        state.camera_connected=True
        state.recording=True
        state.record_mode='ui'
        state.status='RECORDING STARTED - WITH UI'
        state.status_until=time.monotonic()+5
        ui=DVPUI()
        rendered=[]
        ui.text=lambda img,text,*args,**kwargs: rendered.append(str(text))
        ui.draw(np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),np.uint8))
        self.assertIn('REC UI',rendered)
        self.assertIn('RECORDING STARTED - WITH UI',rendered)

    def test_status_message_remains_visible_when_controls_are_hidden(self):
        state.camera_connected=True
        state.ui_visible=False
        state.status='CONTROLS HIDDEN'
        state.status_until=time.monotonic()+5
        ui=DVPUI()
        rendered=[]
        ui.text=lambda img,text,*args,**kwargs: rendered.append(str(text))
        ui.draw(np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),np.uint8))
        self.assertIn('CONTROLS HIDDEN',rendered)
        self.assertNotIn('REC RAW',rendered)

    def test_completed_usb_result_remains_visible_after_drive_removal(self):
        state.camera_connected=True
        state.status_until=0
        state.usb_safe_to_remove=False
        state.usb_last_result='complete'
        ui=DVPUI()
        rendered=[]
        ui.text=lambda img,text,*args,**kwargs: rendered.append(str(text))
        ui.draw(np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),np.uint8))
        self.assertIn('LAST USB EXPORT COMPLETE',rendered)
        self.assertIn('TOUCH READY',rendered)

class InputAndCameraTests(Base):
    def test_absent_camera_waits_without_emitting_disconnect(self):
        disconnected=Mock()
        camera=CameraManager(on_disconnect=disconnected)

        class MissingCapture:
            def isOpened(self):
                camera.stop_event.set()
                return False
            def release(self):
                pass

        with patch('hardware.camera.cv2.VideoCapture',return_value=MissingCapture()):
            camera._run()
        disconnected.assert_not_called()

    def test_touch_validation_and_stale_command(self):
        for message in ({'type':'touch','event':'down','x':float('nan'),'y':.5},
                        {'type':'touch','event':'down','x':1.1,'y':.5},
                        {'type':'command','command':[]},
                        {'type':'command','command':'POWER_CONFIRM'}):
            with self.assertRaises(ValueError):
                parse_message(json.dumps(message))
        with self.assertRaises(ValueError):
            parse_message('x'*513)
        authenticated={'type':'touch','event':'down','x':.25,'y':.75,
                       'session':'boot-a','seq':1,'key':'correct-secret'}
        parsed=parse_message(json.dumps(authenticated),'correct-secret',require_session=True)
        self.assertNotIn('key',parsed)
        with self.assertRaisesRegex(ValueError,'Authentication'):
            parse_message(json.dumps(authenticated),'wrong-secret',require_session=True)
        handler=TouchHandler(DVPUI(),Mock())
        handler.remote_message({'type':'command','command':'POWER','received_at':time.monotonic()-2})
        self.assertEqual(state.dialog,'')

    def test_remote_hold_stops_when_updates_stop(self):
        handler=TouchHandler(DVPUI(),Mock())
        handler.remote_message({'type':'touch','event':'down','x':30/799,'y':100/479,
                                'received_at':time.monotonic()})
        self.assertEqual(state.zoom,1.5)
        handler.last_touch=time.monotonic()-2
        handler.repeat_due=0
        handler.tick()
        self.assertIsNone(handler.held)
        self.assertEqual(state.zoom,1.5)

    def test_serial_fragments_sequence_dedup_and_loss_timeout(self):
        master,slave=pty.openpty()
        self.addCleanup(os.close,master)
        self.addCleanup(os.close,slave)
        bridge=TouchBridge()
        with patch.object(config,'TOUCH_MODE','serial'), \
             patch.object(config,'TOUCH_SERIAL_PORT',os.ttyname(slave)), \
             patch.object(config,'TOUCH_TIMEOUT_SECONDS',.2):
            bridge.start()
            try:
                time.sleep(.2)
                os.write(master,b'{"type":"hello","session":"boot"}\n')
                os.write(master,b'{"type":"comm')
                os.write(master,b'and","command":"ZOOM_IN","seq":1}\n')
                os.write(master,b'{"type":"command","command":"ZOOM_IN","seq":1}\n')
                os.write(master,b'x'*600+b'\n{"type":"heartbeat","seq":2}\n')
                wait_for(lambda:bridge.last_sequence==2)
                events=bridge.drain()
                self.assertEqual(sum(x['type']=='command' for x in events),1)
                wait_for(lambda:state.touch_status=='LOST')
                self.assertTrue(any(x['type']=='release' for x in bridge.drain()))
            finally:
                bridge.stop()

    def test_udp_auth_session_sequence_and_loss_timeout(self):
        bridge=TouchBridge()
        key='test-secret-at-least-16'
        sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        with patch.object(config,'TOUCH_MODE','udp'), \
             patch.object(config,'TOUCH_UDP_BIND','127.0.0.1'), \
             patch.object(config,'TOUCH_UDP_PORT',0), \
             patch.object(config,'TOUCH_SHARED_KEY',key), \
             patch.object(config,'TOUCH_TIMEOUT_SECONDS',.2):
            bridge.start()
            try:
                wait_for(lambda:bridge.bound_port is not None)
                destination=('127.0.0.1',bridge.bound_port)
                def send(message):
                    sender.sendto(json.dumps(message,separators=(',',':')).encode(),destination)
                send({'type':'hello','session':'boot-a','seq':0,'key':'wrong'})
                time.sleep(.05)
                self.assertNotEqual(state.touch_status,'OK')
                send({'type':'hello','session':'boot-a','seq':0,'key':key})
                send({'type':'touch','event':'down','x':.1,'y':.2,
                      'session':'boot-a','seq':1,'key':key})
                send({'type':'touch','event':'move','x':.2,'y':.2,
                      'session':'boot-a','seq':1,'key':key})  # duplicate
                send({'type':'touch','event':'up','x':.1,'y':.2,
                      'session':'old-boot','seq':2,'key':key})
                send({'type':'heartbeat','session':'boot-a','seq':2,'key':key})
                wait_for(lambda:bridge.last_sequence==2)
                events=bridge.drain()
                self.assertEqual(sum(x.get('event')=='down' for x in events),1)
                self.assertFalse(any(x.get('event') in ('move','up') for x in events))
                wait_for(lambda:state.touch_status=='LOST')
                self.assertTrue(any(x['type']=='release' for x in bridge.drain()))
            finally:
                bridge.stop()

    def test_stale_camera_clears_preview_and_boxes(self):
        from app.app import DVPApplication
        app=DVPApplication(enable_usb=False)
        app.camera.latest=FramePacket(1,time.monotonic()-2,1,np.ones((720,1280,3),np.uint8))
        state.camera_connected=True
        app.detector.result=(time.monotonic(),1,[{'box':(0,0,10,10),'confidence':.9}])
        packet,view,boxes=app.update()
        self.assertIsNone(packet)
        self.assertFalse(view.any())
        self.assertEqual(boxes,[])
        self.assertFalse(state.camera_connected)
        self.assertTrue(any(x[0]=='close' for x in app.recorder.queue))

if __name__=='__main__':
    unittest.main()
