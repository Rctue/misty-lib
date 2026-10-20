// Registers touch skill of Misty and sends events to the internal bus and listens to events from the cloud

misty.Debug("Sense_touch skill has started.");

misty.Set("_touch_active", true);
misty.Set("_last_sensor","");
misty.Set("_waiting_for_timeout", false);

startSkill();

function message(the_message)
{
    return JSON.stringify({ "skill" : "sense_touch",
                            "touch active" : misty.Get("_touch_active"),
                            "message": the_message
                        });
}

function startSkill()
{
    //misty.AddPropertyTest("guardian", "guardian_command", "==", "sense_touch", "string");
    //misty.AddReturnProperty("guardian", "guardian_data");
    misty.RegisterUserEvent("sense_touch", true);
    RegisterTouch();

}

// Respond to User events
function _sense_touch(data)
{
     //let command = data["guardian_command"];    
    let received = data["guardian_data"];
    misty.Debug("-->> sense_touch: External command received -> " + received);
    

    
    //if (command == "sense_touch")
    //{
        switch (received)
        {
            case "on":
                DoStopTimer();
                if (!misty.Get("_touch_active")) DoToggleSleepMode("external command");
                break;
            case "off":
                DoStopTimer();
                if (misty.Get("_touch_active")) DoToggleSleepMode("external command");
                break;
            case "default":
        }
    //}
    
    //misty.TriggerEvent("guardian", "sense_touch", message("command_received"), "");
    
    
}

// Respond to touch events
function RegisterTouch()
{
    misty.Debug("Registering Touch");
    misty.AddReturnProperty("Touched", "SensorPosition");
    misty.AddReturnProperty("Touched", "IsContacted");
    misty.AddReturnProperty("Touched", "created");
    misty.RegisterEvent("Touched", "TouchSensor", 20 ,false);
}

function _Touched(data)
{
    let sensor = data.AdditionalResults[0];
    let isPressed = data.AdditionalResults[1];
    let time_stamp = data.AdditionalResults[2];
    isPressed ? misty.Debug("-->> " + sensor +" is Touched") : misty.Debug(sensor+" is Released");


    if (isPressed)
    {
        misty.Set("_last_sensor", JSON.stringify({"sensor":sensor, "is_pressed":true, "time_stamp":time_stamp}));
        switch (sensor)
        {
            case "Chin":
                if (misty.Get("_touch_active"))
                {//misty.Speak("That tickles.");
                    misty.PlayAudio("037-Eurrt.wav");
//                   the_message = JSON.stringify({"image":"e_Pride.jpg","blinking":true, "time_out":5});
//                   misty.TriggerEvent("display_faces", "sense_touch", the_message, "");
//                   misty.TriggerEvent("emotion_enjoy","sense_touch","","");
                    misty.DisplayImage("e_Admiration.jpg"); // Change eyes
                    misty.Pause(3000);
                    misty.DisplayImage("e_DefaultContent.jpg"); // Change eyes
                }
                break;
            case "HeadRight":
            case "HeadLeft":
            case "HeadFront":
            case "HeadBack":
                if (misty.Get("_touch_active"))
                {
                    misty.PlayAudio("010-Uhm.wav");
                }
                break;
            case "Scruff":
                if (misty.Get("_touch_active"))
                {
                    misty.PlayAudio("007-Eurhura.wav");
                }
                if (misty.Get("_waiting_for_timeout")==false)
                {
                    DoStartTimer()
                }
                break;
            default:
                misty.Debug("-->> Sensor Name '" + sensor + "' is unknown.");
        }

        DoTriggerEvents("touch_detected");

    }
    else
    {
        misty.Set("_last_sensor", JSON.stringify({"sensor":sensor, "is_pressed":false, "time_stamp":time_stamp}));
/*        delta_t = DetectLongPress(sensor, time_stamp);
        if (delta_t > 3000)
        {
            misty.Debug("-->> Long press detected");
            switch (sensor)
            {
                case "Scruff":
  //                  misty.Set("_touch_active", false);
  //                  misty.PlayAudio("020-Whoap.wav");
 //                   DoTriggerEvents("go_to_sleep", sensor);
 //                   break;
                case "HeadRight":
                case "HeadLeft":
                case "HeadFront":
                case "HeadBack":
                case "Chin":
                    DoToggleSleepMode(sensor);
                    break;
            }
        }*/

        if (misty.Get("_waiting_for_timeout"))
        {
            switch (sensor)
            {
                case "Scruff":
                    DoStopTimer();
                    break;
            }
        }
    }
    RegisterTouch();    
}

function DetectLongPress(sensor, time_stamp)
{
    var _last_sensor = misty.Get("_last_sensor");
    var delta_t = 0;

    if (_last_sensor != "")
    {
        var _last_sensor = JSON.parse(_last_sensor);
        if (sensor == _last_sensor.sensor)
        {
            //misty.Debug("--> "+_last_sensor.sensor+" , "+_last_sensor.time_stamp);
            let t_last_time = Date.parse(_last_sensor.time_stamp) //.valueOf();
            //misty.Debug("--->> " + t_last_time);
            let t_current_time = Date.parse(time_stamp) //.valueOf();
            //misty.Debug("--->> " + t_current_time);
            delta_t =  t_current_time - t_last_time;
            misty.Debug("--->> " + delta_t + " ms delayed release detected");
        }
        misty.Set("_last_sensor",""); // reset time tracking of sensor pressed
    }
    
    return delta_t;
}

function DoTriggerEvents(behavior)
{
    switch (behavior)
    {
        case "go_to_sleep":
   
            // goto sleep mode
            //misty.TriggerEvent("display_faces", "sense_touch", JSON.stringify({"image":'e_Sleep.jpg', "blinking":false, "time_out":0}), "");
            //misty.TriggerEvent("behavior_go_to_sleep", "sense_touch", "", "");
            misty.TriggerEvent("emotion_dormi", "sense_touch", "", "");
            var msg = "off";
            misty.TriggerEvent("eye_contact", "sense_touch", JSON.stringify({"guardian_data": msg}) , "");
            //misty.TriggerEvent("listen_voices", "sense_touch", JSON.stringify({"guardian_data": msg}) , "");
            //misty.TriggerEvent("guardian", "sense_touch",JSON.stringify({"tosleep": True}) , "");
            misty.Pause(100)
            misty.TriggerEvent("emotion_dormi", "sense_touch", "", "");
            break;
        case "wake_up":
            misty.TriggerEvent("behavior_wake_up", "sense_touch", "", "");
            var msg = "on";
            misty.TriggerEvent("eye_contact", "sense_touch", JSON.stringify({"guardian_data": msg}) , "");
            //misty.TriggerEvent("listen_voices", "sense_touch", JSON.stringify({"guardian_data": msg}) , "");
            //misty.TriggerEvent("guardian", "sense_touch",JSON.stringify({"tosleep": False}) , "");
            break;
        case "touch_detected":
            var msg = "touch_detected";
            misty.TriggerEvent("eye_contact", "sense_touch", JSON.stringify({"guardian_data": msg}) , "");
            break;
        default:
                   
    }
   
    //the_message = message(behavior);
    //misty.TriggerEvent("guardian", "sense_touch", the_message, "");
            
}

function DoToggleSleepMode(sensor)
{
    if (misty.Get("_touch_active"))
    {
        // go_to_sleep
        misty.Set("_touch_active", false);
        misty.PlayAudio("007-Eurhura.wav");
        DoTriggerEvents("go_to_sleep", sensor);
    }
    else { // wake up
        misty.Set("_touch_active", true);
        misty.PlayAudio("001-OooOooo.wav");
        DoTriggerEvents("wake_up", sensor);
    }
}

function DoStartTimer()
{
    time_out=2000;
    misty.Set("_waiting_for_timeout", true);
    misty.RegisterTimerEvent("timeOutLongPress", time_out, false);
}

function DoStopTimer()
{
    //misty.UnregisterEvent("timeOutLongPress");
    misty.Set("_waiting_for_timeout", false);
}

function _timeOutLongPress(data)
{
//    misty.Debug("-->> Time out occurred");
    if (misty.Get("_waiting_for_timeout"))
    {
        DoStopTimer() // time-out so update boolean state variable    
        var last_sensor = misty.Get("_last_sensor");
        misty.Debug("-->>> was still waiting, so longpress" + last_sensor);
        if (last_sensor != "")
        {
            var last_sensor = JSON.parse(last_sensor);
            switch (last_sensor.sensor)
            {
                case "Scruff":
                //case "HeadRight":
                //case "HeadLeft":
                //case "HeadFront":
                //case "HeadBack":
                //case "Chin":
                    DoToggleSleepMode(last_sensor.sensor);
                    break;
            }
        }
    }
    else {
        // time out ocurred but was not waiting for it, do nothing
    }
    
}
