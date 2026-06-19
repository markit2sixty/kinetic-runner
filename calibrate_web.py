from pynput import mouse, keyboard
import time
import requests
import json

# --- Settings ---
CALIBRATION_DIST_INCHES = 5.0
CALIBRATION_DIST_MM = CALIBRATION_DIST_INCHES * 25.4
WEB_SERVER_URL = "http://localhost:5000"

# Global Tracking
total_mickeys_x = 0
recording = False
last_x = None

def save_calibration_to_web(username, mickeys_per_mm):
    """Save calibration results to web database"""
    try:
        response = requests.post(
            f"{WEB_SERVER_URL}/api/save_calibration",
            json={
                'username': username,
                'mickeys_per_mm': mickeys_per_mm
            },
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ {result['message']}")
            return True
        else:
            print(f"❌ Error saving calibration: {response.json().get('error', 'Unknown error')}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the web server is running at http://localhost:5000")
        return False

def run_failproof_calibration():
    global total_mickeys_x, recording, last_x
    
    print("🎯 POSITIONANALYZER CALIBRATION TEST")
    print("="*50)
    print("This test measures your mouse sensitivity for accurate tracking.")
    print()
    
    # Get username
    username = input("👤 Enter your username: ").strip()
    if not username:
        print("❌ Username required!")
        return
    
    print()
    print("📏 CALIBRATION INSTRUCTIONS:")
    print("1. Place your mouse at the 0-inch mark on a ruler")
    print("2. Press [F8] to start recording")
    print("3. Move your mouse EXACTLY 5 inches to the right")
    print("4. Press [F12] when you reach the 5-inch mark")
    print("5. Keep movements as straight as possible")
    print("-" * 50)
    
    def on_move(x, y):
        global total_mickeys_x, recording, last_x
        
        if recording:
            if last_x is not None:
                # Calculate horizontal delta ONLY
                dx = abs(x - last_x)
                
                # Jitter Filter: Ignore movements smaller than 0.5 units
                if dx > 0.5:
                    total_mickeys_x += dx
                    print(f"📊 Recording... Mickeys: {int(total_mickeys_x)}    ", end='\r')
        
        last_x = x

    def on_press(key):
        global recording
        try:
            if key == keyboard.Key.f8:
                if not recording:
                    print("\n🔴 RECORDING STARTED - Move 5 inches now...")
                    recording = True
            elif key == keyboard.Key.f12:
                if recording:
                    print("\n🔵 RECORDING STOPPED")
                    return False
        except AttributeError:
            pass

    # Start the listeners
    with keyboard.Listener(on_press=on_press) as k_listener:
        with mouse.Listener(on_move=on_move) as m_listener:
            k_listener.join()
    
    # Calculate results
    if total_mickeys_x > 500:
        ratio = total_mickeys_x / CALIBRATION_DIST_MM
        
        print("\n" + "="*50)
        print(f"📈 CALIBRATION RESULTS")
        print(f"Total Mickeys Recorded: {int(total_mickeys_x)}")
        print(f"Your Ratio: {ratio:.2f} mickeys per mm")
        
        # DPI estimation
        theoretical_800 = 31.50
        accuracy = (1 - abs(ratio - theoretical_800) / theoretical_800) * 100
        print(f"Accuracy Match (800 DPI): {accuracy:.1f}%")
        print("="*50)
        
        # Save to web database
        print("\n💾 Saving calibration to your account...")
        if save_calibration_to_web(username, ratio):
            print(f"🎉 Calibration complete! You can now view it on your dashboard.")
            print(f"🌐 Visit: {WEB_SERVER_URL}")
        else:
            print(f"⚠️  Calibration calculated but not saved to web.")
            print(f"📝 Your ratio: {ratio:.2f} mickeys/mm (save this number)")
        
        return ratio
    else:
        print("\n❌ ERROR: Movement too small. Please try again.")
        print("💡 Make sure you move at least 5 inches horizontally")

if __name__ == "__main__":
    print("🔧 Starting PositionAnalyzer Calibration Test...")
    print("🌐 Web server should be running at http://localhost:5000")
    print()
    
    run_failproof_calibration()
    
    print("\n" + "="*50)
    print("✅ Calibration test complete!")
    print("🎮 Next: Download and run the position recorder from your dashboard")
    print("="*50)
    input("\nPress Enter to exit...")