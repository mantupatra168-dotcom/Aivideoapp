// main.dart
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:flutter_tts/flutter_tts.dart';
import 'package:razorpay_flutter/razorpay_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

/// ---------------- CONFIG ----------------
/// Put real values in environment/config — DO NOT commit secrets to repo.
const String API_BASE = "https://your-backend.example.com"; // <- change to your backend URL (Render)
const String RAZORPAY_KEY = "rzp_test_xxx"; // <- set in secure config

/// -----------------------------------------

void main() {
  runApp(const AiVantuApp());
}

class AiVantuApp extends StatelessWidget {
  const AiVantuApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AiVantu',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        primarySwatch: Colors.deepPurple,
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  // Core
  final ImagePicker _picker = ImagePicker();
  File? _pickedImage;
  bool _uploading = false;
  String _script = "";
  String _lang = "hi"; // user can set language for TTS generation (hi/en/ta/bn etc.)

  // Speech -> text
  late stt.SpeechToText _speech;
  bool _isListening = false;
  String _spokenText = "";

  // TTS
  final FlutterTts _tts = FlutterTts();

  // Razorpay
  late Razorpay _razorpay;

  // UI state
  bool _generating = false;
  String? _lastVideoUrl;
  List<String> _gallery = [];

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
    _initTts();
    _initRazorpay();
    _loadGallery();
  }

  Future<void> _initTts() async {
    await _tts.setLanguage("en-IN");
    await _tts.setSpeechRate(0.9);
    await _tts.setPitch(1.0);
  }

  void _initRazorpay() {
    _razorpay = Razorpay();
    _razorpay.on(Razorpay.EVENT_PAYMENT_SUCCESS, _handleRazorpaySuccess);
    _razorpay.on(Razorpay.EVENT_PAYMENT_ERROR, _handleRazorpayError);
    _razorpay.on(Razorpay.EVENT_EXTERNAL_WALLET, (_) {});
  }

  @override
  void dispose() {
    _razorpay.clear();
    _tts.stop();
    super.dispose();
  }

  Future<void> _loadGallery() async {
    try {
      final res = await http.get(Uri.parse("$API_BASE/gallery"));
      if (res.statusCode == 200) {
        final List<dynamic> list = jsonDecode(res.body)['videos'] ?? [];
        setState(() {
          _gallery = list.map((e) => e.toString()).toList();
        });
      }
    } catch (e) {
      // ignore - offline friendly
    }
  }

  // --------------- Speech ---------------
  Future<void> _toggleListening() async {
    if (!_isListening) {
      bool available = await _speech.initialize(onStatus: (s) {
        // debug
      }, onError: (e) {
        _tts.speak("Speech recognition error");
      });
      if (available) {
        setState(() {
          _isListening = true;
        });
        _speech.listen(onResult: (val) {
          setState(() {
            _spokenText = val.recognizedWords;
            _script = _spokenText;
          });
        }, localeId: _lang == "hi" ? "hi_IN" : null, listenMode: stt.ListenMode.confirmation);
      } else {
        _tts.speak("Speech recognition not available on this device");
      }
    } else {
      _speech.stop();
      setState(() {
        _isListening = false;
      });
    }
  }

  // --------------- Image Picker ---------------
  Future<void> _pickImage() async {
    final XFile? picked = await _picker.pickImage(source: ImageSource.gallery, imageQuality: 85);
    if (picked != null) {
      setState(() {
        _pickedImage = File(picked.path);
      });
    }
  }

  // --------------- Upload helper ---------------
  Future<String?> _uploadFile(File file, String kind) async {
    try {
      final uri = Uri.parse("$API_BASE/upload");
      final request = http.MultipartRequest('POST', uri);
      request.fields['kind'] = kind;
      request.files.add(await http.MultipartFile.fromPath('file', file.path, filename: file.path.split("/").last));
      final streamed = await request.send();
      final resp = await http.Response.fromStream(streamed);
      if (resp.statusCode == 200) {
        final body = jsonDecode(resp.body);
        return body['saved'] as String?;
      } else {
        final body = resp.body;
        throw Exception("Upload failed: ${resp.statusCode} ${body}");
      }
    } catch (e) {
      rethrow;
    }
  }

  // --------------- Generate Video ---------------
  Future<void> _generateVideo() async {
    if (_generating) return;
    if (_script.trim().isEmpty && _pickedImage == null) {
      _tts.speak("Please provide script or a character image first");
      return;
    }
    setState(() {
      _generating = true;
    });

    try {
      // Upload image first (if any)
      List<String> imageRel = [];
      if (_pickedImage != null) {
        final saved = await _uploadFile(_pickedImage!, "characters");
        if (saved != null) imageRel.add(saved);
      }

      // Create request to backend generate_video endpoint
      final uri = Uri.parse("$API_BASE/generate_video");
      final request = http.MultipartRequest('POST', uri);
      request.fields['user_email'] = "demo@aivantu.com";
      request.fields['title'] = "Mobile Video ${DateTime.now().millisecondsSinceEpoch}";
      request.fields['script'] = _script;
      request.fields['template'] = "Default";
      request.fields['quality'] = "HD";
      request.fields['lang'] = _lang;
      // If we uploaded images we already sent to uploads/ via /upload; but the backend generate_video accepts files as well.
      // For simplicity, attach picked image again as characters (some backends expect direct files).
      if (_pickedImage != null) {
        request.files.add(await http.MultipartFile.fromPath('characters', _pickedImage!.path));
      }

      final streamed = await request.send();
      final resp = await http.Response.fromStream(streamed);
      if (resp.statusCode == 200) {
        final j = jsonDecode(resp.body);
        if (j['status'] == 'done') {
          final url = j['download_url'] as String?;
          setState(() {
            _lastVideoUrl = url;
          });
          _tts.speak("Video ready. Opening gallery.");
          _loadGallery();
          if (url != null && await canLaunchUrl(Uri.parse(url))) {
            await launchUrl(Uri.parse(url));
          }
        } else {
          // For synchronous generate endpoint it might return status 'rendering' or job id
          _tts.speak("Render started. you will be notified when ready.");
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Render started...")));
        }
      } else {
        final j = resp.body;
        _tts.speak("Video generation failed");
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error ${resp.statusCode}: $j")));
      }
    } catch (e) {
      _tts.speak("Error while generating video");
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Exception: $e")));
    } finally {
      setState(() {
        _generating = false;
      });
    }
  }

  // --------------- Payments ---------------
  void _startRazorpayPayment({required int amountInPaise, required String orderId}) {
    var options = {
      'key': RAZORPAY_KEY,
      'amount': amountInPaise, // in paise
      'name': 'AiVantu',
      'description': 'Credits purchase',
      'order_id': orderId, // optionally create order on backend and pass id
      'prefill': {'contact': '', 'email': 'demo@aivantu.com'},
      'theme': {'color': '#6A1B9A'}
    };

    try {
      _razorpay.open(options);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Razorpay open error: $e")));
    }
  }

  void _handleRazorpaySuccess(PaymentSuccessResponse response) {
    _tts.speak("Payment successful");
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Payment success")));
    // inform backend to verify signature & capture
  }

  void _handleRazorpayError(PaymentFailureResponse response) {
    _tts.speak("Payment failed");
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Payment failed")));
  }

  // PayPal flow (frontend) - typically backend should create order and return approval_url
  Future<void> _startPaypalPayment() async {
    try {
      // backend returns approval url e.g. { "approval_url": "https://www.sandbox.paypal.com/..." }
      final res = await http.post(Uri.parse("$API_BASE/create_paypal_order"), headers: {
        "Content-Type": "application/json"
      }, body: jsonEncode({"amount": "499.00", "currency": "INR", "intent": "CAPTURE"}));
      if (res.statusCode == 200) {
        final j = jsonDecode(res.body);
        final url = j['approval_url'] as String?;
        if (url != null && await canLaunchUrl(Uri.parse(url))) {
          await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
        } else {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("No approval url returned")));
        }
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("PayPal create order failed: ${res.body}")));
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Paypal error: $e")));
    }
  }

  // --------------- UI ---------------
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AiVantu — Video Studio'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              _loadGallery();
            },
          ),
          IconButton(
            icon: const Icon(Icons.headset_mic),
            onPressed: () {
              _tts.speak("Hello! Tap Speak to record your script in Hindi or English.");
            },
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _sectionTitle("Voice Assistant (speech -> script)"),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      minLines: 2,
                      maxLines: 6,
                      decoration: const InputDecoration(
                        labelText: "Script (will be used for TTS)",
                        border: OutlineInputBorder(),
                      ),
                      controller: TextEditingController(text: _script),
                      onChanged: (v) => _script = v,
                    ),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    onPressed: _toggleListening,
                    icon: Icon(_isListening ? Icons.mic : Icons.mic_none),
                    label: Text(_isListening ? "Listening..." : "Speak"),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(children: [
                const Text("Language for TTS: "),
                const SizedBox(width: 8),
                DropdownButton<String>(
                  value: _lang,
                  items: const [
                    DropdownMenuItem(value: "hi", child: Text("Hindi (hi)")),
                    DropdownMenuItem(value: "en", child: Text("English (en)")),
                    DropdownMenuItem(value: "bn", child: Text("Bengali (bn)")),
                    DropdownMenuItem(value: "ta", child: Text("Tamil (ta)")),
                  ],
                  onChanged: (v) {
                    if (v != null) setState(() => _lang = v);
                  },
                )
              ]),
              const SizedBox(height: 18),
              _sectionTitle("Character (image)"),
              if (_pickedImage != null)
                SizedBox(
                  height: 180,
                  child: Image.file(_pickedImage!, fit: BoxFit.cover),
                )
              else
                Container(
                  height: 140,
                  color: Colors.grey.shade200,
                  child: const Center(child: Text("No character image selected")),
                ),
              const SizedBox(height: 8),
              Row(children: [
                ElevatedButton.icon(
                  onPressed: _pickImage,
                  icon: const Icon(Icons.photo),
                  label: const Text("Pick Image"),
                ),
                const SizedBox(width: 8),
                ElevatedButton.icon(
                  onPressed: () async {
                    // Upload and generate
                    if (_pickedImage == null && _script.trim().isEmpty) {
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Add image or script first")));
                      return;
                    }
                    await _generateVideo();
                  },
                  icon: const Icon(Icons.movie),
                  label: _generating ? const Text("Generating...") : const Text("Generate Video"),
                ),
              ]),
              const SizedBox(height: 20),
              _sectionTitle("Payments"),
              Wrap(spacing: 12, children: [
                ElevatedButton(
                  onPressed: () {
                    // Example: create order on backend and call razorpay
                    // For demo we call backend to create order id & amount
                    _createOrderAndPay();
                  },
                  child: const Text("Buy Credits (Razorpay)"),
                ),
                ElevatedButton(
                  onPressed: _startPaypalPayment,
                  child: const Text("Buy Credits (PayPal)"),
                ),
              ]),
              const SizedBox(height: 20),
              _sectionTitle("Gallery"),
              _gallery.isEmpty
                  ? const Text("No videos yet")
                  : Column(
                      children: _gallery.map((url) {
                        return ListTile(
                          leading: const Icon(Icons.videocam),
                          title: Text(url.split("/").last),
                          subtitle: Text(url),
                          onTap: () async {
                            final uri = Uri.parse(url);
                            if (await canLaunchUrl(uri)) await launchUrl(uri);
                          },
                        );
                      }).toList(),
                    ),
              const SizedBox(height: 30),
              Text("Last video: ${_lastVideoUrl ?? "none"}", style: const TextStyle(fontSize: 12, color: Colors.grey)),
              const SizedBox(height: 40),
              const Text("NOTE:", style: TextStyle(fontWeight: FontWeight.bold)),
              const Text(
                "1) Set API_BASE at top to your backend URL. "
                "2) Razorpay requires order_id creation on backend for production (capture/verify). "
                "3) PayPal flow requires server-side integration (create order, return approval_url).",
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _sectionTitle(String t) => Padding(
        padding: const EdgeInsets.only(bottom: 8.0),
        child: Text(t, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
      );

  // Ask backend to create a Razorpay order, then open the checkout
  Future<void> _createOrderAndPay() async {
    try {
      final res = await http.post(Uri.parse("$API_BASE/create_razorpay_order"),
          headers: {"Content-Type": "application/json"},
          body: jsonEncode({"amount": 49900 /* amount in paise e.g. 499.00 INR */}));
      if (res.statusCode == 200) {
        final j = jsonDecode(res.body);
        final orderId = j['order_id'] as String?;
        final amount = j['amount'] as int? ?? 49900;
        if (orderId != null) {
          _startRazorpayPayment(amountInPaise: amount, orderId: orderId);
        } else {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Order creation failed")));
        }
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Order API error: ${res.body}")));
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Create order error: $e")));
    }
  }
}
