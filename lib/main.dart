import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';
import 'package:video_player/video_player.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:flutter_tts/flutter_tts.dart';

void main() {
  runApp(MyApp());
}

class Config {
  static const String apiBase = "https://aivideoapp-kzp6.onrender.com";
}

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AiVantu',
      theme: ThemeData.dark(),
      debugShowCheckedModeBanner: false,
      home: HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  @override
  _HomePageState createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _index = 0;
  final pages = [HomeScreen(), CreateScreen(), GalleryScreen(), VoiceAssistantScreen(), ProfileScreen()];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: pages[_index],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _index,
        onTap: (i) => setState(() => _index = i),
        backgroundColor: Colors.black,
        selectedItemColor: Colors.blueAccent,
        unselectedItemColor: Colors.grey,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: "Home"),
          BottomNavigationBarItem(icon: Icon(Icons.add_box), label: "Create"),
          BottomNavigationBarItem(icon: Icon(Icons.video_library), label: "Gallery"),
          BottomNavigationBarItem(icon: Icon(Icons.mic), label: "Assistant"), // 🎤
          BottomNavigationBarItem(icon: Icon(Icons.person), label: "Profile"),
        ],
      ),
    );
  }
}

// ---------------- VOICE ASSISTANT ----------------
class VoiceAssistantScreen extends StatefulWidget {
  @override
  _VoiceAssistantScreenState createState() => _VoiceAssistantScreenState();
}

class _VoiceAssistantScreenState extends State<VoiceAssistantScreen> {
  late stt.SpeechToText _speech;
  bool _isListening = false;
  String _text = "Tap mic & speak...";
  FlutterTts flutterTts = FlutterTts();

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
  }

  Future<void> _listen() async {
    if (!_isListening) {
      bool available = await _speech.initialize();
      if (available) {
        setState(() => _isListening = true);
        _speech.listen(
          onResult: (val) {
            setState(() => _text = val.recognizedWords);
          },
          localeId: "hi-IN", // Hindi
        );
      }
    } else {
      setState(() => _isListening = false);
      _speech.stop();

      // Backend को भेजो
      var res = await http.post(
        Uri.parse("${Config.apiBase}/assistant"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({"query": _text}),
      );

      if (res.statusCode == 200) {
        var reply = jsonDecode(res.body)["reply"];
        setState(() => _text = reply);

        // 🔊 बोलकर सुनाना
        await flutterTts.setLanguage("hi-IN");
        await flutterTts.speak(reply);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text("Voice Assistant")),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(_text, style: TextStyle(fontSize: 18)),
            SizedBox(height: 20),
            FloatingActionButton(
              onPressed: _listen,
              child: Icon(_isListening ? Icons.stop : Icons.mic),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------- REST FEATURES (same as before) ----------------
// ✅ HomeScreen, CreateScreen, GalleryScreen, ProfileScreen remain as before
// (मैंने पहले जो दिया था वो 그대로 रहेगा, सिर्फ नया VoiceAssistantScreen जोड़ा है)
