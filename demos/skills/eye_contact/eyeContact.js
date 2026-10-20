// Sets Misty's arms and head to a neutral position, and prints a debug
// message that the movement is underway.
misty.Debug("Starting Eye contact skill");

startSkill();

function startSkill()
{
    
    misty.Set("yawRight", -81.4, false);
    misty.Set("yawLeft", 83.6, false);
    misty.Set("pitchUp", -37.8, false);
    misty.Set("pitchDown", 24.6, false);
   // _current_state = ""; // make sure the initial state is void
    //_state_data =  "";
    

    initHeadPose();

    let default_data = {"off" :{"time_out":0, "look_around":0}, //0 is never
                        "standby" :{"time_out":0, "look_around":0}, //0 is never
                        "normal":{"time_out":60000  , "look_around":0},
                        "alert" :{"time_out":30000   , "look_around":0}
                    };
    eye_state = {   "image":"e_DefaultContent.jpg",
                    "blinking": true};
    
    misty.Set("_current_state", "init"); //create a empty state variable on Misty
    misty.Set("_default_data", JSON.stringify(default_data));
    misty.Set("_state_data", JSON.stringify({}));
    //misty.Set("_eye_state",JSON.stringify(eye_state));
    RegisterGuardianEvent();
    //misty.RegisterEvent("KeyPhraseRecognized","KeyPhraseRecognized", 10, false);
    //misty.Debug("KeyPhraseRecognition started. Misty will play a sound and wave when she hears 'Hey Misty'.");
    // read actuator values
    registerYaw();
    registerPitch();
    registerRoll();
    registerFaceDetection(); 

    let current_state = "standby"; //create a default state variable on Misty
    var state_data = default_data[current_state];
    stateMachine(current_state, state_data); // sets and stores new state
}

// Respond to User events
function message(the_message)
{
    return JSON.stringify({ "skill" : "eye_contact",
                            "state" : misty.Get("_current_state"),
                            "message": the_message});
}

function RegisterGuardianEvent(data)
{
    //misty.AddPropertyTest("guardian", "guardian_command", "==", "eye_contact", "string");
    //misty.AddReturnProperty("guardian", "guardian_data");
    misty.RegisterUserEvent("eye_contact", true);
}

function _eye_contact(data)
{
    //if (data["guardian_command"] == "eye_contact")
    //{
   // misty.Debug(JSON.stringify(data));
    misty.Debug("eye_contact: External command received from Source -> " + data.Source + ", Event -> " + data.EventName);
    let current_state = misty.Get("_current_state");
    let default_data = JSON.parse(misty.Get("_default_data"));
    var new_state = current_state;
    var new_data = default_data[new_state];

    switch (data.Source)
    {
        case "listen_voices":
        case "sense_touch":           
        case "cloud_connector":
        case "MyRobotApplication":
            // the AWS system can turn the eye contact skill on or off. When turned on, misty wakes up if standby.
            misty.Debug("External command received from " + data.Source + " -> " + data.guardian_data);
            //misty.Debug(JSON.stringify(data));
            
            switch (data.guardian_data)
            {
                case "touch_detected":
                case "normal":
                    if (current_state != "off")
                    {
                        new_state = "normal"; // revert to normal alertness level and wake-up if standby
                    }
                    break;
                case "on":
                    //misty.Set("_skill_state", "on");
                    new_state = "normal"; // revert to normal alertness level and wake-up if standby
                    break;
                case "off":
                    new_state = "off"; // revert to normal alertness level and wake-up if asleep or standby
                    break;
                case "standby":
                    new_state = "standby";
                    break;
            }
            var new_data = default_data[new_state];
            stateMachine(new_state, new_data);
   
            //var the_message = message("command received"); //"External command received"
            //misty.TriggerEvent("guardian", "eye_contact", the_message, "");
            break;
        default:
    }
}


// Start registering Actuator position of the head
// ========================= Reading Head Yaw and Pitch ==========================

function registerYaw() 
{
    misty.AddReturnProperty("headYaw", "SensorId");
    misty.AddReturnProperty("headYaw", "Value");
    misty.AddPropertyTest("headYaw", "SensorId", "==", "ahy", "string");
    misty.RegisterEvent("headYaw", "ActuatorPosition", 200, true);
}

function registerPitch() 
{
    misty.AddReturnProperty("headPitch", "SensorId");
    misty.AddReturnProperty("headPitch", "Value");
    misty.AddPropertyTest("headPitch", "SensorId", "==", "ahp", "string");
    misty.RegisterEvent("headPitch", "ActuatorPosition", 200, true);
}

function registerRoll() 
{
    misty.AddReturnProperty("headRoll", "SensorId");
    misty.AddReturnProperty("headRoll", "Value");
    misty.AddPropertyTest("headRoll", "SensorId", "==", "ahr", "string");
    misty.RegisterEvent("headRoll", "ActuatorPosition", 200, true);
}

function _headYaw(data) 
{
    var headYaw = data.AdditionalResults[1];
    // misty.Debug(headYaw);
    if (!isNaN(headYaw)) misty.Set("headYaw", headYaw, false);
}

function _headPitch(data) 
{
    var headPitch = data.AdditionalResults[1];
    // misty.Debug(headPitch);   
    if (!isNaN(headPitch)) misty.Set("headPitch", headPitch, false);
}

function _headRoll(data) 
{
    var headRoll = data.AdditionalResults[1];
    // misty.Debug(headRoll);   
    if (!isNaN(headRoll)) misty.Set("headRoll", headRoll, false);
}


// ================================ Calibrate =================================
// Misty moves the head right left down up and records the max reachable angles.

// The calibration is not mandatory everytime. Run this once and look at the debug console 
// for the pitch and yaw min max range limits. Update the four global variables 
// listed below with the limits and comment out the call to calibrate funtion 
// "_ = caliberate();"

/*
misty.Pause(2000);

function caliberate()
{
    misty.MoveHead(0, 0, -90, null, 2);
    misty.Pause(4000);
    misty.Set("yawRight", misty.Get("headYaw"), false);
    misty.Debug("Yaw Right Recorded :" + misty.Get("yawRight").toString());

    misty.MoveHead(0, 0, 90, null, 2);
    misty.Pause(4000);
    misty.Set("yawLeft", misty.Get("headYaw"), false);
    misty.Debug("Yaw Left Recorded :" + misty.Get("yawLeft").toString());

    misty.MoveHead(90, 0, 0, null, 2);
    misty.Pause(4000);
    misty.Set("pitchDown", misty.Get("headPitch"), false);
    misty.Debug("Pitch Down Recorded :" + misty.Get("pitchDown").toString());

    misty.MoveHead(-90, 0, 0, null, 2);
    misty.Pause(4000);
    misty.Set("pitchUp", misty.Get("headPitch"), false);
    misty.Debug("Pitch Up Recorded :" + misty.Get("pitchUp").toString());

    misty.Debug("CALIBRATION COMPLETE");
    misty.MoveHead(0, 0, 0, null, 2);
    
    return 0;
}
_ = caliberate();
 */


// Sets up our FaceRecognition event listener.
function registerFaceDetection() {
    // Creates a property test for FaceDetect event messages to check
    // whether the message has a "Label" value before passing
    // the event message into the callback.
    misty.AddPropertyTest("FaceDetect", "Label", "exists", "", "string");

/*
    FaceRecognition{
    "EventName":"MyFaceRecognition",
    "Message":{
      "Bearing":-3,
      "Created":"2018-07-02T16:26:20.1718422Z",
      "Distance":71,
      "Elevation":3,
      "Expiry":"2018-07-02T16:26:20.9218446Z",
      "PersonName":"Face_1",
      "Label": "Face_1",
      "SensorId":null,
      "SensorID":null,
      "TrackId":0
    },
    "Type":"FaceRecognition"
}
*/

    misty.AddReturnProperty("FaceDetect", "Label");
    misty.AddReturnProperty("FaceDetect", "Bearing");
    misty.AddReturnProperty("FaceDetect", "Elevation");
    misty.AddReturnProperty("FaceDetect", "Distance");

    // Registers a new event listener for FaceRecognition events. (We
    // call this event listener FaceDetect, but you can use any name
    // you like. Giving event listeners a custom name means you can
    // create multiple event listeners for the same type of event in a
    // single skill.) Our FaceDetect event listener has a debounce of
    // 1000 ms, and we set the fourth argument (keepAlive) to true,
    // which tells the system to keep listening for FaceDetect events
    // after the first message comes back.
    misty.RegisterEvent("FaceDetect", "FaceRecognition", 1000, true);
}

// Defines how Misty should respond to FaceDetect event messages. Data
// from each FaceDetect event is passed into this callback function.
function _FaceDetect(data) {
    // Stop reading actuators during computation and movevement of head?
    //misty.UnregisterEvent("HeadYaw"); 
    //misty.UnregisterEvent("HeadPitch"); 
    //misty.UnregisterEvent("HeadRoll"); 
    //misty.UnregisterEvent("FaceDetect"); // stop misty from responding to new events
    
    let label = data.AdditionalResults[0]; // or data.PropertyTestResults[0].PropertyParent.Label etc.
    let bearing = data.AdditionalResults[1];
    let elevation = data.AdditionalResults[2];
    let distance = data.AdditionalResults[3];
    //misty.Debug("Label: " + label + ", Bearing: " + bearing+ ", Elevation: " + elevation+ ", Distance: " + distance);

    
    const headYaw = misty.Get("headYaw");
    const headPitch = misty.Get("headPitch");
    const yawRight = misty.Get("yawRight");
    const yawLeft = misty.Get("yawLeft");
    const pitchUp = misty.Get("pitchUp");
    const pitchDown = misty.Get("pitchDown");

    const camera_angle = {"horizontal": 106, "vertical": 60};

    //var new_pitch = headPitch + ((pitchDown - pitchUp) / 33) * elevation; // -13 up and +13 down // unclear in which units bearing and elevation are given
    //var new_yaw   = headYaw   + ((yawLeft - yawRight) / 66) * bearing; // -13 right and +13 left
    var new_pitch = headPitch + (camera_angle.vertical / 33) * elevation; // -13 up and +13 down // unclear in which units bearing and elevation are given
    var new_yaw   = headYaw   + (camera_angle.horizontal /66) * bearing; // -13 right and +13 left
    var new_roll = 0.8  * misty.Get("headRoll"); // slowly reduce head roll
    if ( !( isNaN(new_pitch) || isNaN(new_yaw) || isNaN(new_roll)) )
    {
        // clip values to maximum range
        if (new_pitch < pitchUp)        new_pitch = pitchUp;
        else if (new_pitch > pitchDown) new_pitch = pitchDown;
        if (new_yaw > yawLeft)          new_yaw = yawLeft;
        else if (new_yaw < yawRight)    new_yaw = yawRight;
        
        // move the robot's head
        misty.Debug(new_pitch + " , " + new_yaw );
        misty.MoveHeadDegrees(new_pitch, new_roll , new_yaw, 80); // Faces head forward

        // update headpose to new values;
        misty.Set("headYaw"  , new_yaw, false);
        misty.Set("headPitch", new_pitch, false);
        misty.Set("headRoll", new_roll, false);
    }

    // Restore reading actuator values
    //registerYaw();
    //registerPitch();
    //registerRoll();
    //registerFaceDetection();


/*    var current_state = misty.Get("state");
    var state_data = JSON.parse(misty.Get("state_data"));
    if (current_state == "normal")
    {
        current_state = "track_face";
        //state_data[next_state].time_out = 5000;
        //state_date[next_state].look_around = 5;
    }
*/  
    let current_state = misty.Get("_current_state");
    let default_data = JSON.parse(misty.Get("_default_data"));
    let state_data = JSON.parse(misty.Get("_state_data"));

    switch (current_state)
    {
        case "normal":
        case "alert": // resets lookout behaviour
            var new_state = "alert";
            var new_data = default_data[new_state];
            break;
        //case "standby": // should not be possible as face detection is off in this state
        default:
            var new_state = current_state;
            var new_data = state_data;
    }
    //registerFaceDetection(); // restart face
    misty.TriggerEvent("guardian", "eye_contact",JSON.stringify({"skill":"eye_contact","face_detected": true}) , "");
    stateMachine(new_state, new_data); // updates eyes and registers events based on the state
    
}


// Sets Misty's arms, head, LED, and display image to a neutral configuration.
function initHeadPose()
{
    misty.Pause(100);
    misty.MoveHeadDegrees(0, 0, 0, 50); // Faces head forward
    misty.Set("headYaw", 0.0);
    misty.Set("headPitch", 0.0);
    misty.Set("headRoll", 0.0);
}



/*
// Sets up our FaceRecognition event listener.
function registerFaceRec() {
    // Creates a property test for FaceRec event messages to check
    // whether the message has a "Label" value before passing
    // the event message into the callback.
    misty.AddPropertyTest("FaceRec", "Label", "exists", "", "string");
    // Registers a new event listener for FaceRecognition events. (We
    // call this event listener FaceRec, but you can use any name
    // you like. Giving event listeners a custom name means you can
    // create multiple event listeners for the same type of event in a
    // single skill.) Our FaceRec event listener has a debounce of
    // 1000 ms, and we set the fourth argument (keepAlive) to true,
    // which tells the system to keep listening for FaceRec events
    // after the first message comes back.
    misty.RegisterEvent("FaceRec", "FaceRecognition", 1000, true);
}

// Defines how Misty should respond to FaceRec event messages. Data
// from each FaceRec event is passed into this callback function.
function _FaceRec(data) {
    // Gets the value of the Label property in the FaceRecognition
    // event message.
    var faceDetected = data.PropertyTestResults[0].PropertyValue;

    // Tells Misty how to react if the face is unknown.
    if (faceDetected == "unknown person") {
        misty.ChangeLED(255, 0, 0); // Changes LED to red
        misty.DisplayImage("e_Disgust.jpg"); // Raises eyebrows
        misty.MoveArmDegrees("both", 70, 100); // Raises both arms
    }
    // Tells Misty how to react when she sees you. Replace
    // "<Your-Name>" below with the label you have trained Misty to
    // associate with your face.
    else if (faceDetected == "Johnathan") {
        misty.ChangeLED(148, 0, 211); // Changes LED to purple
        misty.DisplayImage("e_Joy.jpg"); // Shows happy eyes
        misty.MoveArmDegrees("both", -80, 100); // Raises both arms
    }

    // Registers for a timer event to invoke the _timeoutToNormal
    // callback function after 5000 milliseconds.
    misty.RegisterTimerEvent("timeoutToNormal", 5000, false);
}

registerFaceRec();
*/

function lookSidetoSide()
{   
 
    if (misty.Get("headYaw") > 0) misty.MoveHead(getRandomInt(-20, 0), 0, -40, null, 4);
    else misty.MoveHead(getRandomInt(-20, 0), 0, 40, null, 4);
 
}

function getRandomInt(min, max) 
{
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function changeEyes()
{
    let current_state = misty.Get("_current_state");
    let eye_state = JSON.parse(misty.Get("_eye_state"));
    //misty.Debug("Entering change eyes: " + skill_state + ", eye_state: " + JSON.stringify(eye_state));

    switch(current_state)
    {
        case "off":
            misty.ChangeLED(0, 0, 0); // Changes LED to off
            new_image = "e_Sleeping.jpg";
            new_blink = false;
            misty.TriggerEvent("behavior_go_to_sleep", "eye_contact", "", "");
            break;           
        case "standby":
            misty.ChangeLED(0, 0, 0); // Changes LED to off
            new_image = "e_Sleepy2.jpg"; // Show sleeping eyes
            new_blink = false;  // turn blinking off
            misty.TriggerEvent("behavior_go_to_standby", "eye_contact", "", "");
            break;
        case "normal":
            misty.ChangeLED(255, 255, 255); // Changes LED to white
            new_image = "e_DefaultContent.jpg"; // Show default eyes
            new_blink =true;
            misty.TriggerEvent("behavior_go_to_normal", "eye_contact", "", "");
            break;
        case "alert":
            misty.ChangeLED(0, 255, 0); // Changes LED to green
            new_image = "e_Joy.jpg"; // Show default eyes
            new_blink = true;
            misty.TriggerEvent("behavior_go_to_alert", "eye_contact", "", "");
            break;
        default:
            misty.ChangeLED(148, 0, 211); // Changes LED to purple
            new_image = "e_Surprise.jpg"; // Show default eyes
            new_blink = true;
            misty.TriggerEvent("emotion_surprised", "eye_contact", "", "");
            break;
    }

    if (eye_state.image != new_image) // necessary to prevent flashing due to repeated calls
    {
        misty.DisplayImage(new_image); // Change eyes
        eye_state.image = new_image;
    }
    if (eye_state.blinking != new_blink)
    {
        misty.SetBlinking(new_blink); // turn blinking on/off
        eye_state.blinking = new_blink;
    }
    misty.Set("_eye_state", JSON.stringify(eye_state));
}

// callback for timer event
function _timeOutLogic(callbackData)
{
    // by default the new state is the same as the current state
    let current_state = misty.Get("_current_state");
    let state_data = JSON.parse(misty.Get("_state_data"));
    let default_data  = JSON.parse(misty.Get("_default_data"));

    //misty.Debug("Entering time_out logic: " + current_state + " , " + JSON.stringify(state_data));
    var new_state = current_state;
    var new_data = state_data;
    switch (current_state)
    {
        case "off":
            break;
        case "standby":
            // misty wakes after standby
            new_state = "normal";
            new_data = default_data[new_state];
            break;
        case "normal":
            // no faces detected, look around a few minutes then go to standby
            if (new_data.look_around > 0)
            {
                lookSidetoSide();
                new_data.look_around -=1;
            }
            else
            {
 
                new_state = "standby";
                new_data = default_data[new_state];
            }
            break;
        case "alert":
            // face no longer detected, start looking around or go back to normal
            if (new_data.look_around > 0)
            {
                lookSidetoSide();
                new_data.look_around -=1;
            }
            else
            {
                new_state = "normal";
                new_data = default_data[new_state];
            }
            break;
        default:
            break;
    }
    stateMachine(new_state, new_data); //update state and register new timer event
}

function stateMachine(new_state, new_data)
{   
    //misty.Debug("Entering state machine: " + new_state);
    //misty.Debug(JSON.stringify(new_data));
    let current_state = misty.Get("_current_state");
    let state_data = JSON.parse(misty.Get("_state_data"));

    if (new_state != current_state)
    {
        switch (new_state)
        {
            case "off":
                misty.StopFaceDetection();
                misty.UnregisterEvent("timeOutLogic");
                //misty.Set("_skill_state", "off");
                break;           
            case "standby":
                // Stop face recognition
                misty.StopFaceDetection();
                //misty.UnregisterEvent("FaceDetect");

                initHeadPose(); 
            
                // Stop reading actuators?
                //misty.UnregisterEvent("headYaw"); 
                //misty.UnregisterEvent("headPitch"); 
                //misty.UnregisterEvent("headRoll"); 
    
                break;
            case "normal":            
            case "alert":
                // start face recognition
//                registerFaceDetection();
                // Starts Misty's face detection process, so we can register for
                // (and receive) FaceRecognition event messages.
                misty.StopFaceDetection(); // is this necessary?
                misty.StartFaceDetection();
                break;
            default:
                break;
        }
        misty.Set("_current_state", new_state);
    }
    
    if (state_data != new_data)
    {
        misty.Set("_state_data", JSON.stringify(new_data));
    };
    
    changeEyes(); // the eyes reflect the state of the robot
    
    
    // Registers for a timer event to invoke the _timeoutToNormal
// callback function after 5000 milliseconds.

    if (new_state != "off")
    {

        //misty.Debug("time_out in _state_data and new_data: " + _state_data.time_out);
        misty.Debug("state -> " + new_state + ", time_out -> " + new_data.time_out + ", look_around -> " + new_data.look_around);
        //misty.UnregisterEvent("timeOutLogic");
        if (new_data.time_out > 0) misty.RegisterTimerEvent("timeOutLogic", new_data.time_out, false);
    }
}

