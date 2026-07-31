import AudioToolbox
import CoreAudio
import Foundation

/// Finds and pins capture to the Mac's built-in microphone specifically,
/// regardless of whatever the system's current default input device is.
///
/// Confirmed decision (2026-07-30): voice recognition accuracy was
/// noticeably worse over AirPods -- a real, known macOS/Bluetooth
/// limitation, not a bug in this app. Using a Bluetooth headset for BOTH
/// input and output forces macOS into HFP (Hands-Free Profile), an old,
/// low-bandwidth, call-quality codec (as low as 8kHz mono) -- dramatically
/// worse than any real microphone, built-in or otherwise. Every app
/// hits this, not just this one.
///
/// Rather than ask Joshua to manually switch System Settings' input
/// device every time, VoiceInput.swift pins CAPTURE specifically to the
/// built-in mic via Core Audio, leaving playback (VoiceOutput's TTS)
/// completely untouched -- it keeps using whatever's actually connected
/// (AirPods, speakers), since output quality was never the problem.
enum BuiltInMicSelector {
    /// Returns the AudioDeviceID of the Mac's built-in microphone, if one
    /// exists on this machine (identified by transport type, not by name
    /// -- names vary by Mac model, transport type does not).
    static func builtInInputDeviceID() -> AudioDeviceID? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        var dataSize: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize)
        guard status == noErr, dataSize > 0 else { return nil }

        let deviceCount = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: deviceCount)
        status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize, &deviceIDs)
        guard status == noErr else { return nil }

        for deviceID in deviceIDs {
            guard isBuiltIn(deviceID), hasInputStreams(deviceID) else { continue }
            return deviceID
        }
        return nil
    }

    /// Forces `audioUnit` (the AVAudioEngine input node's underlying unit)
    /// to capture from `deviceID` specifically. Must be called before the
    /// engine starts, after the input node has been accessed at least
    /// once (which lazily creates the audio unit).
    static func setInputDevice(_ deviceID: AudioDeviceID, on audioUnit: AudioUnit) {
        var mutableDeviceID = deviceID
        AudioUnitSetProperty(
            audioUnit,
            kAudioOutputUnitProperty_CurrentDevice,
            kAudioUnitScope_Global,
            0,
            &mutableDeviceID,
            UInt32(MemoryLayout<AudioDeviceID>.size)
        )
    }

    private static func isBuiltIn(_ deviceID: AudioDeviceID) -> Bool {
        var transportType: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyTransportType,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        let status = AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &transportType)
        return status == noErr && transportType == kAudioDeviceTransportTypeBuiltIn
    }

    private static func hasInputStreams(_ deviceID: AudioDeviceID) -> Bool {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreams,
            mScope: kAudioObjectPropertyScopeInput,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        let status = AudioObjectGetPropertyDataSize(deviceID, &address, 0, nil, &size)
        return status == noErr && size > 0
    }
}
