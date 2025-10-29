import { useState, useEffect, useRef } from 'react';
import './VoiceAssistant.css';

const VoiceAssistant = () => {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('Nothing yet...');
  const [response, setResponse] = useState('Waiting for your input...');
  const [status, setStatus] = useState('Ready to listen');
  const [buttonText, setButtonText] = useState('Click to Talk');
  const [buttonState, setButtonState] = useState('ready'); // ready, listening, processing

  const recognitionRef = useRef(null);
  const synthesisRef = useRef(window.speechSynthesis);

  useEffect(() => {
    initializeSpeechRecognition();
    requestMicrophonePermission();
    
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, []);

  const initializeSpeechRecognition = () => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      showError('Speech recognition not supported in this browser');
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognitionRef.current = new SpeechRecognition();

    recognitionRef.current.continuous = false;
    recognitionRef.current.interimResults = false;
    recognitionRef.current.lang = 'en-US';

    recognitionRef.current.onstart = () => {
      setIsListening(true);
      setButtonState('listening');
      updateUI('listening', 'Listening... Click to stop', 'Stop Listening');
    };

    recognitionRef.current.onresult = (event) => {
      const speechResult = event.results[0][0].transcript;
      setTranscript(speechResult);
      setButtonState('processing');
      updateUI('processing', 'Processing your request...', 'Processing...');
      processInput(speechResult);
    };

    recognitionRef.current.onerror = (event) => {
      console.error('Speech recognition error:', event.error);
      handleSpeechError(event.error);
    };

    recognitionRef.current.onend = () => {
      setIsListening(false);
      setButtonState('ready');
      updateUI('ready', 'Ready to listen', 'Click to Talk');
    };
  };

  const requestMicrophonePermission = async () => {
    try {
      await navigator.mediaDevices?.getUserMedia({ audio: true });
      console.log('Microphone permission granted');
    } catch (error) {
      console.warn('Microphone permission not granted:', error);
    }
  };

  const toggleListening = () => {
    if (!recognitionRef.current) {
      showError('Speech recognition not available');
      return;
    }

    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  };

  const startListening = () => {
    try {
      recognitionRef.current.start();
    } catch (error) {
      showError('Could not start speech recognition');
    }
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  };

  const handleSpeechError = (error) => {
    let errorMessage = 'Sorry, I couldn\'t understand you. Please try again.';

    switch (error) {
      case 'no-speech':
        errorMessage = 'No speech detected. Please try again.';
        break;
      case 'audio-capture':
        errorMessage = 'Microphone not accessible. Please check permissions.';
        break;
      case 'not-allowed':
        errorMessage = 'Microphone permission denied. Please allow microphone access.';
        break;
    }

    showError(errorMessage);
  };

  const processInput = async (input) => {
    try {
      const aiResponse = generateSimpleResponse(input);
      setResponse(aiResponse);
      speak(aiResponse);
    } catch (error) {
      showError('Error processing your request');
    }
  };

  const generateSimpleResponse = (input) => {
    const lowerInput = input.toLowerCase();

    if (lowerInput.includes('hello') || lowerInput.includes('hi')) {
      return 'Hello! How can I help you today?';
    } else if (lowerInput.includes('time')) {
      return `The current time is ${new Date().toLocaleTimeString()}.`;
    } else if (lowerInput.includes('date')) {
      return `Today is ${new Date().toLocaleDateString()}.`;
    } else if (lowerInput.includes('weather')) {
      return 'I don\'t have access to weather data right now, but you can check your local weather app or website.';
    } else if (lowerInput.includes('name')) {
      return 'I\'m your React voice assistant. You can call me whatever you\'d like!';
    } else if (lowerInput.includes('help')) {
      return 'I can help you with basic questions about time, date, and simple conversations. Just click the button and start talking!';
    } else if (lowerInput.includes('react')) {
      return 'Yes! I\'m built with React and Vite. Pretty cool, right?';
    } else {
      return `You said: "${input}". I'm a React-powered voice assistant demo. For a full AI experience, integrate with ChatGPT or Claude API!`;
    }
  };

  const speak = (text) => {
    synthesisRef.current.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.9;
    utterance.pitch = 1;
    utterance.volume = 1;

    const voices = synthesisRef.current.getVoices();
    const preferredVoice = voices.find(voice => 
      voice.name.includes('Google') || 
      voice.name.includes('Microsoft') || 
      voice.lang.includes('en-US')
    );
    
    if (preferredVoice) {
      utterance.voice = preferredVoice;
    }

    utterance.onend = () => {
      setButtonState('ready');
      updateUI('ready', 'Ready to listen', 'Click to Talk');
    };

    synthesisRef.current.speak(utterance);
  };

  const updateUI = (state, statusText, btnText) => {
    setStatus(statusText);
    setButtonText(btnText);
  };

  const showError = (message) => {
    setStatus(message);
    setResponse(message);
    setButtonState('ready');
    updateUI('error', message, 'Click to Talk');

    setTimeout(() => {
      updateUI('ready', 'Ready to listen', 'Click to Talk');
    }, 3000);
  };

  return (
    <div className="voice-assistant-container">
      <h1>React Voice Assistant</h1>
      
      <div className="voice-interface">
        <button 
          className={`voice-button ${buttonState}`}
          onClick={toggleListening}
        >
          <div className="mic-icon">🎤</div>
          <span className="button-text">{buttonText}</span>
        </button>
        
        <div className="status">{status}</div>
        
        <div className="transcript-container">
          <div className="section">
            <h3>What you said:</h3>
            <div className="transcript">{transcript}</div>
          </div>
          
          <div className="section">
            <h3>Assistant response:</h3>
            <div className="response">{response}</div>
          </div>
        </div>
      </div>
      
      <div className="instructions">
        <p><strong>How to use:</strong></p>
        <ul>
          <li>Click the microphone button to start speaking</li>
          <li>Speak your question or command</li>
          <li>Click again to stop recording</li>
          <li>The assistant will process and respond</li>
        </ul>
        <p><em>Built with React + Vite. Try saying "Hello", "What time is it?", or "Tell me about React"!</em></p>
      </div>
    </div>
  );
};

export default VoiceAssistant;