from mistyPy.Robot import Robot
from mistyPy.Events import Events
from mistyPy.EventFilters import EventFilters

import time
import threading
import random

misty = None

class misty_state:
    yawRight = -90.0
    yawLeft = 90.0
    pitchUp = -90.0
    pitchDown = 90.0
    headPitch =0.0
    headYaw = 0.0
    findFace = False
    
def registerYaw():
    # misty.AddReturnProperty("headYaw", "SensorId");
    # misty.AddReturnProperty("headYaw", "Value");
    # misty.AddPropertyTest("headYaw", "SensorId", "==", "ahy", "string");
    # misty.RegisterEvent("headYaw", "ActuatorPosition", 100, true);
    pitch = misty.register_event(Events.ActuatorPosition, "pitch", condition=[EventFilters.ActuatorPosition.HeadPitch], keep_alive=True, callback_function=log_headPitch, debounce=100)
        


def registerPitch():
    # misty.AddReturnProperty("headPitch", "SensorId");
    # misty.AddReturnProperty("headPitch", "Value");
    # misty.AddPropertyTest("headPitch", "SensorId", "==", "ahp", "string");
    # misty.RegisterEvent("headPitch", "ActuatorPosition", 100, true);
    pitch = misty.register_event(Events.ActuatorPosition, "yaw", condition=[EventFilters.ActuatorPosition.HeadYaw], keep_alive=True, callback_function=log_headYaw, debounce=100)



def log_headYaw(data):
    headpose_data = data['message']
    timestamp = headpose_data['created'][:-1].replace('T',' ')
    sensor_id = headpose_data['sensorId']
    misty_state.headYaw = headpose_data['value']
    

def log_headPitch(data):
    headpose_data = data['message']
    timestamp = headpose_data['created'][:-1].replace('T',' ')
    sensor_id = headpose_data['sensorId']
    misty_state.headPitch = headpose_data['value']

def log_faceLocation(data):
    faceLocation = data['message']
    misty_state.faceLocation = faceLocation 
# // ================================ Calibrate =================================
# // Misty moves the head right left down up and records the max reachable angles.

# // The calibration is not mandatory everytime. Run this once and look at the debug console 
# // for the pitch and yaw min max range limits. Update the four global variables 
# // listed below with the limits and comment out the call to calibrate funtion 
# // "_ = caliberate();"

def calibrate():
    misty.move_head(0, 0, -90, duration=2)
    time.sleep(4)
    misty_state.yawRight = misty_state.headYaw
    print("Yaw Right Recorded :" + str(misty_state.yawRight))

    misty.move_head(0, 0, 90, duration=2)
    time.sleep(4)
    misty_state.yawLeft = misty_state.headYaw
    print("Yaw Left Recorded :" + str(misty_state.yawLeft))

    misty.move_head(90, 0, 0, duration=2)
    time.sleep(4)
    misty_state.pitchDown = misty_state.headPitch
    print("Pitch Down Recorded :" + str(misty_state.pitchDown))

    misty.move_head(-90, 0, 0, duration=2)
    time.sleep(4)
    misty_state.pitchUp = misty_state.headPitch
    print("Pitch Up Recorded :" + str(misty_state.pitchUp))

    print("CALIBRATION COMPLETE")
    misty.move_head(0, 0, 0, duration=2)
    
    return misty_state

# // ============================ Face Recognition Data and Face Follow =========================

def registerFaceRec():
    misty.register_event(Events.FaceRecognition, "FaceRec", keep_alive=True, callback_function=_FaceRec, debounce=1300)
    t=threading.Timer(6,_findFace)
    t.start()

def _FaceRec(data):
    if (misty_state.findFace):
        misty_state.findFace = False
        misty.change_led(0, 255, 0)
        misty.display_image("e_Love.jpg")
    
    ### not sure what will be in data 
    ### need to print and check the structure of the data to get the correct properties for face label, bearing and elevation
    data = data['message']
    faceDetected = data['Label'] #data.PropertyTestResults[0].PropertyParent.Label; # //PersonName 
    bearing = data['Bearing'] #data.PropertyTestResults[0].PropertyParent.Bearing; # // -13 right and +13 left
    elevation = data['Elevation'] #data.PropertyTestResults[0].PropertyParent.Elevation; # // -13 up and +13 down
    print(faceDetected)

    if (bearing != 0 and elevation != 0):
        misty.move_head(misty_state.headPitch + ((misty_state.pitchDown - misty_state.pitchUp) / 33) * elevation, 0, misty_state.headYaw + ((misty_state.yawLeft - misty_state.yawRight) / 66) * bearing, 7 / abs(bearing))
    elif (bearing != 0):
        misty.move_head( 0, 0, misty_state.headYaw + ((misty_state.yawLeft - misty_state.yawRight) / 66) * bearing, 7 / abs(bearing))
    else:
        misty.move_head(misty_state.headPitch + ((misty_state.pitchDown - misty_state.pitchUp) / 33) * elevation, 0, 0, 5 / abs(elevation))


    t=threading.Timer(6, _findFace)
    t.start()


# // ========================== Lost Face - Search Mode =======================

def _findFace():
    misty_state.findFace = True
    misty.change_led(0, 0, 255)
    misty.display_image("e_DefaultContent.jpg")


def lookSidetoSide(interval=6.5):
    if (misty_state.findFace):
        if (misty_state.headYaw > 0):
            misty.move_head(random.randint(-20,0), 0, -40, duration=4)
        else:
            misty.move_head(random.randint(-20, 0), 0, 40, duration=4)
            
    t=threading.Timer(interval, lookSidetoSide, args=[interval]) # start a new timer as soon as the previous timer finishes its task
    t.start()
    
if __name__ == "__main__":
    ROBOT_IP = "192.168.0.100"
    misty = Robot(ROBOT_IP)
    
    time.sleep(2)

    registerPitch()
    registerYaw()
    
    _ = calibrate()

    misty.stop_face_recognition()
    misty.start_face_recognition()

    registerFaceRec()
    lookSidetoSide(6.5) # misty checks every 6.5 seconds if it has lost the face and if so, it starts looking side to side to find the face again.

    
    misty.keep_alive()

