document.addEventListener("DOMContentLoaded", () => {
  // Utility: Get current page by body id
  const page = document.body.getAttribute("data-page");

  // === Common Components ===
  if (page) {
    console.log(`Loaded: ${page}`);
  }

  // === MAP INITIALIZATION ===
  if (document.getElementById("map")) {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        position => {
          initMap(position.coords.latitude, position.coords.longitude);
        },
        () => initMap()
      );
    } else {
      initMap();
    }
  }

  function initMap(lat = -1.286389, lng = 36.817223) {
    const location = { lat: parseFloat(lat), lng: parseFloat(lng) };
    const map = new google.maps.Map(document.getElementById("map"), {
      zoom: 14,
      center: location
    });

    new google.maps.Marker({
      position: location,
      map: map
    });
  }

  // === FORM VALIDATION ===
  if (page === "signup") {
    const signupForm = document.querySelector("form[action='/signup']");
    if (signupForm) {
      signupForm.addEventListener("submit", (e) => {
        const email = signupForm.querySelector("input[name='email']");
        const password = signupForm.querySelector("input[name='password']");
        const name = signupForm.querySelector("input[name='name']");

        if (!email.value.includes("@")) {
          alert("Please enter a valid email.");
          e.preventDefault();
        }
        if (password.value.length < 6) {
          alert("Password must be at least 6 characters.");
          e.preventDefault();
        }
        if (name.value.trim() === "") {
          alert("Name cannot be empty.");
          e.preventDefault();
        }
      });
    }
  }

  // === DASHBOARD DYNAMIC LOADING ===
  if (page === "dashboard") {
    // Sample dynamic section, e.g., load houses
    console.log("Load dashboard data here.");
  }

  // === CHAT ===
  if (page === "chat") {
    const sendBtn = document.getElementById("sendMessage");
    const messageBox = document.getElementById("message");
    const messageList = document.getElementById("messages");

    if (sendBtn && messageBox && messageList) {
      sendBtn.addEventListener("click", () => {
        const msg = messageBox.value.trim();
        if (msg !== "") {
          const div = document.createElement("div");
          div.className = "user-message";
          div.textContent = msg;
          messageList.appendChild(div);
          messageBox.value = "";
          // TODO: Add socket.io emit if real-time
        }
      });
    }
  }

  // === Dark Mode Toggle ===
  const themeToggle = document.getElementById('themeToggle');
  const body = document.getElementById('body');
  const icon = themeToggle ? themeToggle.querySelector('i') : null;

  if (themeToggle && icon) {
    themeToggle.addEventListener('click', () => {
      body.classList.toggle('dark-mode');
      if (body.classList.contains('dark-mode')) {
        icon.classList.replace('fa-moon', 'fa-sun');
        localStorage.setItem('theme', 'dark');
      } else {
        icon.classList.replace('fa-sun', 'fa-moon');
        localStorage.setItem('theme', 'light');
      }
    });

    // Load saved theme
    if (localStorage.getItem('theme') === 'dark') {
      body.classList.add('dark-mode');
      icon.classList.replace('fa-moon', 'fa-sun');
    }
  } else {
    console.warn('Theme toggle element not found');
  }
});