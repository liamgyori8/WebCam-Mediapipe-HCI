import string
import ctypes
import cv2
import mediapipe as mp
import pyautogui
import time
from faster_whisper import WhisperModel
import sounddevice as sd
import threading
import queue
from collections import deque
from PyQt6.QtWidgets import QApplication, QLabel, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen
import sys

PEN_WIDTH = 4
ERASER_RADIUS = 36
FINGER_WIDTH = 6

def set_overlay(text):
    global last_overlay_text, last_overlay_update

    now = time.time()
    if text == last_overlay_text and now - last_overlay_update < 0.15:
        return

    last_overlay_text = text
    last_overlay_update = now
    overlay_thread.set_text(text)


class DrawOverlay(QWidget):

    def __init__(self):
        super().__init__()

        self.points = []
        self.lines = []
        self.mode = "nothing"

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.showFullScreen()

    def paintEvent(self, event):

        painter = QPainter(self)

        if self.mode == "show":
            pen = QPen(Qt.GlobalColor.red)
            pen.setWidth(FINGER_WIDTH)
            painter.setPen(pen)
            for line in self.lines:
                start_point, end_point = line
                painter.drawLine(
                    start_point[0],
                    start_point[1],
                    end_point[0],
                    end_point[1]
                )
            painter.setPen(QPen(Qt.GlobalColor.blue))
            for point in self.points:
                if point is None:
                    continue
                painter.drawEllipse(point[0] - 6, point[1] - 6, 12, 12)
        else:        
            pen = QPen(Qt.GlobalColor.green)
            pen.setWidth(PEN_WIDTH)

            painter.setPen(pen)

            for i in range(1, len(self.points)):
                if self.points[i - 1] is None or self.points[i] is None:
                    continue

                painter.drawLine(
                    self.points[i - 1][0],
                    self.points[i - 1][1],
                    self.points[i][0],
                    self.points[i][1]
                )

    def erase_at(self, x, y, radius):
        radius_squared = radius * radius
        erased_points = []
        previous_was_erased = False

        for point in self.points:
            if point is None:
                if erased_points and erased_points[-1] is not None:
                    erased_points.append(None)
                previous_was_erased = False
                continue

            point_x, point_y = point
            should_erase = (point_x - x) ** 2 + (point_y - y) ** 2 <= radius_squared

            if should_erase:
                if erased_points and erased_points[-1] is not None:
                    erased_points.append(None)
                previous_was_erased = True
            else:
                if previous_was_erased and erased_points and erased_points[-1] is not None:
                    erased_points.append(None)
                erased_points.append(point)
                previous_was_erased = False

        while erased_points and erased_points[-1] is None:
            erased_points.pop()

        self.points = erased_points


class OverlayThread:

    def __init__(self):
        self.commands = queue.Queue()
        self.app = QApplication(sys.argv)
        self.label = QLabel("Tracking")
        self.label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 150);
            color: lime;
            font-size: 24px;
            padding: 10px;
            border-radius: 10px;
        """)

        self.label.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.label.move(20, 20)
        self.label.resize(600, 100)
        self.label.show()

        self.draw_overlay = DrawOverlay()
        self.running = True

    def process_commands(self):
        while True:
            try:
                command, payload = self.commands.get_nowait()
            except queue.Empty:
                break

            if command == "text":
                self.label.setText(payload)
                self.label.adjustSize()
            elif command == "mode":
                self.draw_overlay.mode = payload
            elif command == "clear":
                self.draw_overlay.points.clear()
                self.draw_overlay.lines.clear()
                self.draw_overlay.update()
            elif command == "show_points":
                points, lines = payload
                self.draw_overlay.points = points
                self.draw_overlay.lines = lines
                self.draw_overlay.update()
            elif command == "append_point":
                self.draw_overlay.points.append(payload)
                self.draw_overlay.update()
            elif command == "erase":
                x, y, radius = payload
                self.draw_overlay.erase_at(x, y, radius)
                self.draw_overlay.update()
            elif command == "stop":
                self.running = False

        self.app.processEvents()

    def set_text(self, text):
        self.commands.put(("text", text))

    def set_mode(self, mode):
        self.commands.put(("mode", mode))

    def clear(self):
        self.commands.put(("clear", None))

    def set_show_points(self, points, lines):
        self.commands.put(("show_points", (points, lines)))

    def append_point(self, point):
        self.commands.put(("append_point", point))

    def erase_at(self, x, y, radius):
        self.commands.put(("erase", (x, y, radius)))

    def stop(self):
        self.commands.put(("stop", None))
        self.process_commands()
        self.label.close()
        self.draw_overlay.close()
        self.app.quit()


def keep_window_on_top(window_name):
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
        if hwnd:
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            HWND_TOPMOST = -1
            ctypes.windll.user32.SetWindowPos(hwnd,HWND_TOPMOST, 0,0, 0,0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,)
            return True
    except Exception as e:
        print("Topmost window failed:", e)
    return False


def move_cursor(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def smooth_landmark_points(hand_landmarks):
    smoothed_points = []

    for index, landmark in enumerate(hand_landmarks):
        mapped_x = (landmark.x - tracking_margin) / (1 - 2 * tracking_margin)
        mapped_y = (landmark.y - tracking_margin) / (1 - 2 * tracking_margin)

        screen_x = min(max(int(mapped_x * screen_w), 0), screen_w - 1)
        screen_y = min(max(int(mapped_y * screen_h), 0), screen_h - 1)

        hand_point_histories[index].append((screen_x, screen_y))
        avg_screen_x = sum(point[0] for point in hand_point_histories[index]) / len(hand_point_histories[index])
        avg_screen_y = sum(point[1] for point in hand_point_histories[index]) / len(hand_point_histories[index])

        previous_point = previous_hand_points[index]
        if previous_point is None:
            previous_point = (avg_screen_x, avg_screen_y)

        curr_x = previous_point[0] + (avg_screen_x - previous_point[0]) * smoothening
        curr_y = previous_point[1] + (avg_screen_y - previous_point[1]) * smoothening

        previous_hand_points[index] = (curr_x, curr_y)
        smoothed_points.append((curr_x, curr_y))

    return smoothed_points

command_queue = deque(maxlen=10)
command_queue_lock = threading.Lock()
running = True
last_overlay_text = ""
last_overlay_update = 0

overlay_thread = OverlayThread()

def audio_worker():
    while running:
        audio = sd.rec(
            int(3 * fs),
            samplerate=fs,
            channels=1,
            dtype='int16'
        )
        sd.wait()

        audio_float = audio.flatten().astype("float32") / 32768.0

        segments, info = model.transcribe(audio_float, language="en", vad_filter=True, condition_on_previous_text=False, beam_size=5)

        raw_text = " ".join(
            segment.text
            for segment in segments
        )
        raw_text = raw_text.strip()
        raw_text = raw_text.translate(str.maketrans('', '', string.punctuation))
        raw_text = raw_text.lower()

        if raw_text:
            with command_queue_lock:
                command_queue.append(raw_text)

            print("Heard:", raw_text)

fs = 16000

model = WhisperModel("base",device="cpu",compute_type="int8")
gesture_model_path = "gesture_recognizer.task"

BaseOptions = mp.tasks.BaseOptions
GestureRecognizer = mp.tasks.vision.GestureRecognizer
GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
VisionRunningMode = mp.tasks.vision.RunningMode


gesture_options = GestureRecognizerOptions(
    base_options=BaseOptions(model_asset_path=gesture_model_path),
    running_mode=VisionRunningMode.VIDEO,
    num_hands=1
)

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

cap.set(cv2.CAP_PROP_FPS, 60)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 500)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 500)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

window_name = "Hand + Gesture Tracking"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
cv2.resizeWindow(window_name, 500, 500)
cv2.moveWindow(window_name, 0, 0)
keep_window_on_top(window_name)

screen_w, screen_h = pyautogui.size()

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0

prev_scroll_y = 0
last_click_time = 0
click_threshold = 0.035
smoothening = 0.50
movement_deadzone = 2
tracking_margin = 0.08
hand_point_histories = [deque(maxlen=1) for _ in range(21)]
previous_hand_points = [None] * 21

audio_thread = threading.Thread(target=audio_worker, daemon=True)

with GestureRecognizer.create_from_options(gesture_options) as recognizer:
    
    audio_thread.start()

    typing_mode = False

    draw_mode = False

    break_draw = False

    show_hand = False

    try:

        while True:

            with command_queue_lock:
                command = command_queue.popleft() if command_queue else ""

            if typing_mode:
                 
                 if "stop" in command or "exit" in command or "quit" in command:
                    typing_mode = False
                    draw_mode = False
                    set_overlay("Mode: Normal")
                    print("Exited typing mode")
                 elif "undo" in command:
                    pyautogui.hotkey("ctrl", "z")
                 elif command:
                    pyautogui.write(command + " ")
            else: 
                if "click" in command:
                    pyautogui.click()
                elif "drag" in command:
                    pyautogui.mouseDown()
                elif "drop" in command:
                    pyautogui.mouseUp()
                elif "enter" in command:
                    pyautogui.press("enter")
                elif command.startswith("type "):
                    pyautogui.write(command[5:] + " ")
                elif command == "type":
                    typing_mode = True
                    set_overlay("Mode: Typing")
                    print("Entering typing mode")
                elif "open" in command:
                    pyautogui.mouseDown()
                    pyautogui.mouseUp()
                    pyautogui.mouseDown()
                    pyautogui.mouseUp()
                elif "delete" in command or "backspace" in command:
                    pyautogui.press("backspace")
                elif "draw" in command: 
                    draw_mode = True
                    overlay_thread.clear()
                    overlay_thread.set_mode("draw")
                    set_overlay("Mode: Draw")
                    print("Entering draw mode")
                
                elif "stop" in command or "exit" in command or "quit" in command:
                    draw_mode = False
                    show_hand = False
                    overlay_thread.clear()
                    set_overlay("Mode: Normal")
                    print("Exited draw mode")
                elif "show" in command:
                    set_overlay("Mode: show hand")
                    show_hand = True
                    overlay_thread.set_mode("show")
                elif "hide" in command: 
                    set_overlay("Mode: Normal")
                    show_hand = False
                    overlay_thread.clear()
                

            success, frame = cap.read()

            if not success:
                print("Failed to read frame")
                break

            frame = cv2.flip(frame, 1)

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

           
            mp_image = mp.Image( image_format=mp.ImageFormat.SRGB,data=rgb_frame)

            timestamp = int(time.time() * 1000)

            result = recognizer.recognize_for_video(mp_image,timestamp)

        
            if result.hand_landmarks:
                for hand_landmarks in result.hand_landmarks:

                    h, w, _ = frame.shape

                    for landmark in hand_landmarks:

                        x = int(landmark.x * w)
                        y = int(landmark.y * h)

                        cv2.circle( frame,(x, y),5,(0, 255, 0),-1)

                    index_tip = hand_landmarks[8]
                    middle_tip = hand_landmarks[12]
                    ring_tip = hand_landmarks[16]
                    pinky_tip = hand_landmarks[20]
                    thumb_tip = hand_landmarks[4]
                    palm_base = hand_landmarks[0]

                    x1 = int(index_tip.x * w)
                    y1 = int(index_tip.y * h)

                    previous_cursor_point = previous_hand_points[8]
                    smoothed_hand_points = smooth_landmark_points(hand_landmarks)

                    curr_x1, curr_y1 = smoothed_hand_points[8]
                    curr_x2, curr_y2 = smoothed_hand_points[12]
                    curr_x3, curr_y3 = smoothed_hand_points[16]
                    curr_x4, curr_y4 = smoothed_hand_points[20]
                    curr_x5, curr_y5 = smoothed_hand_points[4]

                    if previous_cursor_point is not None:
                        if abs(curr_x1 - previous_cursor_point[0]) > movement_deadzone or abs(curr_y1 - previous_cursor_point[1]) > movement_deadzone:
                            move_cursor(curr_x1, curr_y1)

                    gesture = None
                    confidence = 0

                    if result.gestures:
                        gesture = result.gestures[0][0].category_name
                        confidence = result.gestures[0][0].score
                    
                    if show_hand:
                        overlay_points = []
                        for point_x, point_y in smoothed_hand_points:
                            overlay_points.append((int(point_x), int(point_y)))

                        hand_connections = [
                            (0, 1), (1, 2), (2, 3), (3, 4),
                            (0, 5), (5, 6), (6, 7), (7, 8),
                            (0, 9), (9, 10), (10, 11), (11, 12),
                            (0, 13), (13, 14), (14, 15), (15, 16),
                            (0, 17), (17, 18), (18, 19), (19, 20),
                            (5, 9), (9, 13), (13, 17)
                        ]
                        overlay_lines = []
                        for start_index, end_index in hand_connections:
                            overlay_lines.append((
                                overlay_points[start_index],
                                overlay_points[end_index]
                            ))

                        overlay_thread.set_show_points(overlay_points, overlay_lines)

                    if draw_mode:
                        if gesture == "Closed_Fist":
                            overlay_thread.erase_at(int(curr_x1), int(curr_y1), ERASER_RADIUS)
                        else:
                            overlay_thread.append_point((int(curr_x1), int(curr_y1)))

                    pinch_distance = ((index_tip.x - thumb_tip.x) ** 2 + (index_tip.y - thumb_tip.y) ** 2) ** 0.5
                    if pinch_distance < click_threshold and time.time() - last_click_time > 1.0:
                        pyautogui.click()
                        last_click_time = time.time()
                        set_overlay("Pinch Click")

                    cv2.circle(frame,(x1, y1),15,(255, 0, 255),-1)

                    if gesture:
                        if typing_mode:
                            if gesture == "Open_Palm":
                                pyautogui.press("enter")
                            elif gesture == "Closed_Fist":
                                pyautogui.press("backspace")
                            set_overlay(f"Mode: Typing\nGesture: {gesture}" )
                        elif draw_mode:
                            set_overlay(f"Mode: Draw\nGesture: {gesture}" )
                        elif show_hand:
                            set_overlay(f"Mode: Show Hand\nGesture: {gesture}" )
                        else:
                            set_overlay(f"Mode: Normal\nGesture: {gesture}" )
                        if gesture == "Thumb_Up":
                            pyautogui.scroll(100)
                        elif gesture == "Open_Palm":
                            break_draw = True

                        elif gesture == "Thumb_Down":
                            pyautogui.scroll(-100)
                        elif gesture == "Victory":
                            if index_tip.y < 0.5:
                                pyautogui.scroll(-100)
                            else:
                                pyautogui.scroll(100)

            cv2.imshow(window_name, frame)
            overlay_thread.process_commands()
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
            running = False
            cap.release()
            cv2.destroyAllWindows()
            audio_thread.join(timeout=2)
            overlay_thread.stop()
            print("Shutdown complete.")
