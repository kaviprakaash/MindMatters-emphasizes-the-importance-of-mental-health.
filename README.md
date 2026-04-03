# Mental Wellness Assistant

A full-stack web application built with Flask (Python) for backend and HTML/CSS/JavaScript for frontend to help users track their mental wellness.


## ✨ Features

- **🔐 Secure Authentication**: User registration and login with password hashing
- **📊 Advanced Mood Tracker**: Daily mood logging with visual emoji selection and journaling
- **🤖 AI-Powered Chatbot**: ML-driven assistant using transformers for emotion detection
   - Real-time sentiment analysis and emotion recognition
   - Conversational flow with acknowledgment, questions, and actions
   - Context memory using Flask sessions
   - Overthinking pattern detection and breaker responses
   - Crisis detection with safe, supportive responses
   - Randomized responses to avoid repetition
   - Practical coping techniques (breathing exercises, grounding, productivity tasks)
- **🧠 Overthinking Breaker**: Interactive thought analysis with timer functionality
- **📈 Dashboard**: Vertical list of tools (mood, chat, overthinking, medication); mood chart lives on Mood Tracker
- **💊 Prescription Insight**: Upload a prescription image/PDF or type a medicine name to get AI-powered drug information
   - Supports both file upload (image/PDF) and manual medicine entry
   - Uses OCR to extract medicine names from prescriptions
   - Fetches drug info from OpenFDA and local mappings (supports Indian and international brands)
   - Summarizes use, side effects, and safety info in a user-friendly card
   - Handles missing info gracefully with clear user messages
- **🎨 Professional UI**: Modern, clean design with gradients, shadows, and smooth animations

## 🚀 Installation

1. Clone or download the project
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python app.py
   ```
4. Open http://127.0.0.1:5000 in your browser

## 🏗️ Project Structure

```
mental_health/
├── app.py                 # Main Flask application with advanced chatbot
├── models.py              # Database models and setup
├── requirements.txt       # Python dependencies including transformers
├── templates/             # Professional HTML templates
│   ├── base.html         # Modern layout with gradients and icons
│   ├── login.html        # Clean authentication forms
│   ├── register.html     # User registration interface
│   ├── dashboard.html    # Professional dashboard with cards
│   ├── mood_tracker.html # Interactive mood logging
│   ├── chat.html         # Modern chat interface
│   └── overthinking.html # Thought analysis tool
└── static/                # Frontend assets
    ├── css/              # Custom styles
    └── js/               # Interactive JavaScript
        ├── mood_chart.js # Mood trend chart (Mood Tracker page)
        ├── chat.js       # Chat functionality with modern UI
        └── overthinking.js # Timer and analysis features
```

## 🗄️ Database

Uses SQLite with three tables:
- `users`: User accounts with secure password storage
- `mood_logs`: Daily mood entries with timestamps
- `chat_history`: AI conversation history

## 🤖 AI Chatbot Features

The chatbot uses advanced ML with the following capabilities:

- **🧠 Sentiment Analysis**: Uses Hugging Face `transformers` model for accurate emotion detection
- **😊 Emotion Recognition**: Detects stress, anxiety, sadness, anger, happiness, and neutral states
- **💬 Conversational Flow**: Structured responses with acknowledgment, follow-up questions, and actionable suggestions
- **🧠 Context Awareness**: Remembers previous conversation topics and emotions
- **🔄 Overthinking Detection**: Identifies patterns like "what if", "overthinking", "can't stop thinking"
- **🚨 Crisis Response**: Safe handling of critical situations with appropriate support messaging
- **🎲 Response Variety**: Randomized responses to maintain engagement
- **🛡️ Coping Techniques**: Provides practical breathing exercises, grounding techniques, and productivity tasks

## 🎨 Professional Design Features

- **🌈 Modern Color Scheme**: Gradient backgrounds and professional color palette
- **📱 Responsive Design**: Works perfectly on desktop, tablet, and mobile
- **✨ Smooth Animations**: Hover effects, transitions, and micro-interactions
- **🎯 Visual Hierarchy**: Clear typography and spacing for better UX
- **🔍 Accessibility**: Proper contrast, focus states, and semantic HTML
- **📊 Interactive Charts**: Beautiful Chart.js visualizations
- **💫 Loading States**: Skeleton screens and progress indicators
- **🎨 Icon Integration**: Font Awesome icons for visual clarity

## ⚠️ Disclaimer

This application is not a medical or professional mental health service. Please consult qualified professionals for serious mental health concerns.

## 🛠️ Technologies Used

- **Backend**: Flask, SQLite, Werkzeug, Transformers (Hugging Face), Torch
- **Frontend**: HTML5, Tailwind CSS, JavaScript (ES6+), Chart.js, Font Awesome
- **AI/ML**: Hugging Face Transformers for sentiment analysis
- **Database**: SQLite for data persistence
- **Styling**: Tailwind CSS with custom gradients and animations