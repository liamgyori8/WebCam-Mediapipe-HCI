import string
import ctypes
import cv2
import mediapipe as mp
import pyautogui
import time
from faster_whisper import WhisperModel
import sounddevice as sd
import threading
from collections import deque
from PyQt6.QtWidgets import QApplication, QLabel, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen
import sys

app = QApplication(sys.argv)

label = QLabel("Tracking")
label.setStyleSheet("""
    background-color: rgba(0, 0, 0, 150);
    color: lime;
    font-size: 24px;
    padding: 10px;
    border-radius: 10px;
""")

label.setWindowFlags(
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.Tool
)

label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
label.setAttribute(
    Qt.WidgetAttribute.WA_TransparentForMouseEvents
)

label.move(20, 20)
label.resize(600, 100)
label.show()

def set_overlay(text):
    global last_overlay_text, last_overlay_update

    now = time.time()
    if text == last_overlay_text and now - last_overlay_update < 0.15:
        return

    last_overlay_text = text
    last_overlay_update = now
    label.setText(text)
    label.adjustSize()
    app.processEvents()


class DrawOverlay(QWidget):

    def __init__(self):
        super().__init__()

        self.points = []

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

        pen = QPen(Qt.GlobalColor.green)
        pen.setWidth(4)

        painter.setPen(pen)

        for i in range(1, len(self.points)):
            painter.drawLine(
                self.points[i - 1][0],
                self.points[i - 1][1],
                self.points[i][0],
                self.points[i][1]
            )


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

latest_command = ""
latest_command_lock = threading.Lock()
running = True
last_overlay_text = ""
last_overlay_update = 0

draw_overlay = DrawOverlay()

def audio_worker():
    global latest_command

    while running:
        audio = sd.rec(
            int(2 * fs),
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

        with latest_command_lock:
            latest_command = raw_text

        if latest_command:
            print("Heard:", latest_command)

fs = 16000

model = WhisperModel("base",device="cpu",compute_type="int8")
gesture_model_path = ('C:\\Users\\liam\\Documents\\GitHub\\Hand_Control\\gesture_recognizer.task')

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

prev_x = None
prev_y = None
prev_scroll_y = 0
last_click_time = 0
cursor_history = deque(maxlen=1)
click_threshold = 0.05
smoothening = 0.50
movement_deadzone = 2
tracking_margin = 0.08

audio_thread = threading.Thread(target=audio_worker, daemon=True)

with GestureRecognizer.create_from_options(gesture_options) as recognizer:
    
    audio_thread.start()

    typing_mode = False

    draw_mode = False

    break_draw = False

    try:

        while True:

            with latest_command_lock:
                command = latest_command
                if command:
                    latest_command = ""

            if typing_mode:
                 
                 if "stop" in command or "exit" in command or "quit" in command:
                    typing_mode = False
                    draw_mode = False
                    set_overlay("Mode: Normal")
                    print("Exited typing mode")
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
                elif "delete" in command or "backspace" in command:
                    pyautogui.press("backspace")
                elif "draw" in command: 
                    draw_mode = True
                    draw_overlay.points.clear()
                    draw_overlay.update()
                    set_overlay("Mode: Draw")
                    print("Entering draw mode")
                elif "stop" in command or "exit" in command or "quit" in command:
                    draw_mode = False
                    draw_overlay.points.clear()
                    draw_overlay.update()
                    set_overlay("Mode: Normal")
                    print("Exited draw mode")

            success, frame = cap.read()

            if not success:
                print("Failed to read frame")
                break

            frame = cv2.flip(frame, 1)

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

           
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb_frame
            )

            timestamp = int(time.time() * 1000)

            result = recognizer.recognize_for_video(
                mp_image,
                timestamp
            )

        
            if result.hand_landmarks:
                for hand_landmarks in result.hand_landmarks:

                    h, w, _ = frame.shape

                    for landmark in hand_landmarks:

                        x = int(landmark.x * w)
                        y = int(landmark.y * h)

                        cv2.circle( frame,(x, y),5,(0, 255, 0),-1)

                    index_tip = hand_landmarks[8]
                    middle_tip = hand_landmarks[12]
                    thumb_tip = hand_landmarks[4]
                    palm_base = hand_landmarks[0]

                    x = int(index_tip.x * w)
                    y = int(index_tip.y * h)

                    x2 = int(middle_tip.x * w)
                    y2 = int(middle_tip.y * h)

                    mapped_x = (index_tip.x - tracking_margin) / (1 - 2 * tracking_margin)
                    mapped_y = (index_tip.y - tracking_margin) / (1 - 2 * tracking_margin)

                    screen_x = min(max(int(mapped_x * screen_w), 0), screen_w - 1)
                    screen_y = min(max(int(mapped_y * screen_h), 0), screen_h - 1)

                    cursor_history.append((screen_x, screen_y))
                    avg_screen_x = sum(pt[0] for pt in cursor_history) / len(cursor_history)
                    avg_screen_y = sum(pt[1] for pt in cursor_history) / len(cursor_history)

                    if prev_x is None or prev_y is None:
                        prev_x = avg_screen_x
                        prev_y = avg_screen_y

                    curr_x = prev_x + (avg_screen_x - prev_x) * smoothening
                    curr_y = prev_y + (avg_screen_y - prev_y) * smoothening

                    if abs(curr_x - prev_x) > movement_deadzone or abs(curr_y - prev_y) > movement_deadzone:
                        move_cursor(curr_x, curr_y)

                    prev_x = curr_x
                    prev_y = curr_y

                    if draw_mode:
                        draw_overlay.points.append((int(curr_x), int(curr_y)))
                        draw_overlay.update()
                        app.processEvents()

                    pinch_distance = ((index_tip.x - thumb_tip.x) ** 2 + (index_tip.y - thumb_tip.y) ** 2) ** 0.5
                    if pinch_distance < click_threshold and time.time() - last_click_time > 0.5:
                        pyautogui.click()
                        last_click_time = time.time()
                        set_overlay("Pinch Click")

                    cv2.circle(frame,(x, y),15,(255, 0, 255),-1)

                    if result.gestures:

                        gesture = result.gestures[0][0].category_name
                        confidence = result.gestures[0][0].score

                        if typing_mode:
                            set_overlay(f"Mode: Typing\nGesture: {gesture}" )
                        elif draw_mode:
                            set_overlay(f"Mode: Draw\nGesture: {gesture}" )
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

            if typing_mode:
                if command and ("stop" in command or "exit" in command or "quit" in command):
                    typing_mode = False
                    set_overlay("Mode: Normal")
                    print("Exited typing mode")

                elif command:
                    pyautogui.write(command + " ")
                    set_overlay(f"Typing: {command}")

            cv2.imshow(window_name, frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
            running = False
            cap.release()
            cv2.destroyAllWindows()
            audio_thread.join(timeout=2)
            print("Shutdown complete.")
            label.close()
            app.quit()
