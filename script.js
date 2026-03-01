document.addEventListener('DOMContentLoaded', function () {
    // ------------------------------------------------------------------------
    // Theme Toggle Logic
    // ------------------------------------------------------------------------
    const themeToggleBtn = document.getElementById('theme-toggle');
    const htmlEl = document.documentElement;

    let isDark = false;
    htmlEl.setAttribute('data-theme', 'light');

    themeToggleBtn.addEventListener('click', () => {
        isDark = !isDark;
        htmlEl.setAttribute('data-theme', isDark ? 'dark' : 'light');
        themeToggleBtn.innerHTML = isDark ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-stars"></i>';
        updateChartTheme(isDark);
    });

    // ------------------------------------------------------------------------
    // Notification Bell Logic
    // ------------------------------------------------------------------------
    const notifDot = document.getElementById('notifDot');
    const notifDropdown = document.getElementById('notifDropdown');
    const notifEmpty = document.getElementById('notifEmpty');
    const notifBell = document.getElementById('notifBell');

    function checkNotificationCount() {
        fetch('/notifications/count')
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (data && data.unread_count > 0) {
                    notifDot?.classList.remove('d-none');
                } else {
                    notifDot?.classList.add('d-none');
                }
            })
            .catch(() => { });
    }

    // Poll for new notifications every 30 seconds
    checkNotificationCount();
    setInterval(checkNotificationCount, 30000);

    // Fetch and render notifications when the bell dropdown opens
    if (notifBell) {
        notifBell.addEventListener('show.bs.dropdown', function () {
            fetch('/notifications')
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    notifDot?.classList.add('d-none'); // clear dot after open
                    if (!data || !data.notifications || data.notifications.length === 0) {
                        if (notifEmpty) notifEmpty.style.display = 'block';
                        return;
                    }
                    if (notifEmpty) notifEmpty.style.display = 'none';

                    // Remove old items (keep header + empty)
                    notifDropdown.querySelectorAll('.notif-item').forEach(el => el.remove());

                    data.notifications.forEach(n => {
                        const li = document.createElement('li');
                        li.className = 'notif-item';
                        li.innerHTML = `
                            <a class="dropdown-item small py-2 px-3 border-bottom ${n.is_read ? 'text-muted' : 'fw-semibold'}" href="${n.link}">
                                <i class="bi bi-lightning-charge text-warning me-2"></i>${n.message}
                                <span class="d-block text-muted" style="font-size:0.7rem">${new Date(n.created_at).toLocaleString()}</span>
                            </a>`;
                        notifDropdown.appendChild(li);
                    });
                })
                .catch(() => { });
        });
    }

    // Language Dropdown Handler
    document.querySelectorAll('.lang-selector').forEach(item => {
        item.addEventListener('click', function (e) {
            e.preventDefault();
            const lang = this.getAttribute('data-lang');
            fetch('/set_language', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ language: lang })
            })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        window.location.reload();
                    } else {
                        console.error('Failed to switch language', data.message);
                    }
                })
                .catch(err => console.error('Language switch error:', err));
        });
    });

    // ------------------------------------------------------------------------
    // Elements
    // ------------------------------------------------------------------------
    const analyzeBtn = document.getElementById('analyzeBtn');
    const activityInput = document.getElementById('activityInput');
    const leadershipVal = document.getElementById('leadershipVal');
    const employabilityVal = document.getElementById('employabilityVal');
    const leadershipPath = document.getElementById('leadershipPath');
    const employabilityPath = document.getElementById('employabilityPath');
    const resumeFeedContainer = document.getElementById('resumeFeedContainer');
    const emptyFeedState = document.getElementById('emptyFeedState');
    const downloadPdfBtn = document.getElementById('downloadPdfBtn');

    // ------------------------------------------------------------------------
    // Voice Assistant (Web Speech API)
    // ------------------------------------------------------------------------
    const micBtn1 = document.getElementById('micBtn1');
    const micIcon1 = document.getElementById('micIcon1');
    const q1Input = document.getElementById('q1');
    const btnListenOpps = document.getElementById('btnListenOpps');
    const iconListenOpps = document.getElementById('iconListenOpps');

    // Language mapping for Web Speech API
    let speechLang = 'en-US';
    if (window.CURRENT_LANG === 'hi') speechLang = 'hi-IN';
    if (window.CURRENT_LANG === 'kn') speechLang = 'kn-IN';

    // 1. Speech-to-Text (Microphone)
    if (micBtn1 && q1Input) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = speechLang;
            let isRecording = false;

            micBtn1.addEventListener('click', () => {
                if (!isRecording) recognition.start();
                else recognition.stop();
            });

            recognition.onstart = () => {
                isRecording = true;
                micBtn1.classList.remove('btn-outline-secondary', 'text-muted');
                micBtn1.classList.add('btn-danger', 'text-white');
                if (micIcon1) micIcon1.classList.replace('bi-mic-fill', 'bi-mic-mute-fill');
                q1Input.placeholder = "Listening...";
            };

            recognition.onresult = (e) => {
                q1Input.value = e.results[0][0].transcript;
            };

            recognition.onend = () => {
                isRecording = false;
                micBtn1.classList.remove('btn-danger', 'text-white');
                micBtn1.classList.add('btn-outline-secondary', 'text-muted');
                if (micIcon1) micIcon1.classList.replace('bi-mic-mute-fill', 'bi-mic-fill');
                q1Input.placeholder = "e.g., Managed a household event";
            };

            recognition.onerror = (e) => {
                console.error("Speech recognition error:", e.error);
                recognition.stop();
            };
        } else {
            micBtn1.style.display = 'none';
        }
    }

    // 2. Text-to-Speech (Listen Button)
    window.aiSpeechText = ""; // Holds the dynamic text to read
    if (btnListenOpps) {
        btnListenOpps.addEventListener('click', () => {
            if (!window.aiSpeechText || !window.speechSynthesis) return;

            if (window.speechSynthesis.speaking) {
                window.speechSynthesis.cancel();
                if (iconListenOpps) {
                    iconListenOpps.classList.replace('bi-volume-up-fill', 'bi-volume-mute-fill');
                    setTimeout(() => iconListenOpps.classList.replace('bi-volume-mute-fill', 'bi-volume-up-fill'), 500);
                }
                return;
            }

            const utterance = new SpeechSynthesisUtterance(window.aiSpeechText);
            utterance.lang = speechLang;

            utterance.onstart = () => {
                btnListenOpps.classList.replace('btn-outline-primary', 'btn-primary');
                btnListenOpps.classList.add('text-white');
            };

            utterance.onend = () => {
                btnListenOpps.classList.replace('btn-primary', 'btn-outline-primary');
                btnListenOpps.classList.remove('text-white');
            };

            window.speechSynthesis.speak(utterance);
        });
    }

    // ------------------------------------------------------------------------
    // 5-Point Skill Radar Chart
    // ------------------------------------------------------------------------
    // Single Activity Radar Chart (Step 2)
    const ctx = document.getElementById('skillRadarChart').getContext('2d');

    // Historical Radar Chart (Step 1 Dashboard)
    const historyCtxEl = document.getElementById('historyRadarChart');
    let historyChart;

    // Wizard Elements
    const step1 = document.getElementById('step-1');
    const step2 = document.getElementById('step-2');
    const step3 = document.getElementById('step-3');
    const goToStep3Btn = document.getElementById('goToStep3Btn');
    const restartWizardBtn = document.getElementById('restartWizardBtn');
    const backToStep1Btn = document.getElementById('backToStep1Btn');
    const backToStep2Btn = document.getElementById('backToStep2Btn');

    const radarOptions = (isDark) => ({
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: isDark ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.9)',
                titleColor: isDark ? '#f8fafc' : '#1e293b',
                bodyColor: isDark ? '#e2e8f0' : '#475569',
                borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
                borderWidth: 1,
                padding: 10
            }
        },
        scales: {
            r: {
                min: 0,
                max: 100,
                angleLines: { color: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)' },
                grid: { color: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)' },
                ticks: { display: false },
                pointLabels: {
                    color: isDark ? '#94a3b8' : '#64748b',
                    font: { size: 11, family: "'Inter', sans-serif", weight: '600' }
                }
            }
        }
    });

    // Initialize with 0 values
    const skillRadarChart = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: ['Strategic', 'Financial', 'Crisis', 'Team', 'Emotional'],
            datasets: [{
                label: 'Competency Map',
                data: [0, 0, 0, 0, 0],
                backgroundColor: 'rgba(99, 102, 241, 0.3)',
                borderColor: '#6366f1',
                pointBackgroundColor: '#ec4899',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#ec4899',
                borderWidth: 2,
                tension: 0.3
            }]
        },
        options: radarOptions(false)
    });

    // Fetch and Initialize Dashboard Metrics (Historical Radar)
    if (historyCtxEl) {
        fetch('/dashboard_metrics')
            .then(res => res.ok ? res.json() : null)
            .then(data => {
                if (data && data.status === 'success' && data.leadership_radar) {
                    historyChart = new Chart(historyCtxEl.getContext('2d'), {
                        type: 'radar',
                        data: {
                            labels: data.leadership_radar.labels,
                            datasets: [{
                                label: 'Historical Strength',
                                data: data.leadership_radar.data,
                                backgroundColor: 'rgba(16, 185, 129, 0.2)', // emerald green
                                borderColor: 'rgba(16, 185, 129, 1)',
                                pointBackgroundColor: 'rgba(16, 185, 129, 1)',
                                pointBorderColor: '#fff',
                                borderWidth: 2,
                            }]
                        },
                        options: radarOptions(isDark)
                    });
                }
            })
            .catch(err => console.error("Could not load dashboard metrics", err));
    }

    function updateChartTheme(isDark) {
        skillRadarChart.options = radarOptions(isDark);
        skillRadarChart.update();
        if (historyChart) {
            historyChart.options = radarOptions(isDark);
            historyChart.update();
        }
    }

    // ------------------------------------------------------------------------
    // SVG Gauge Animation Helper
    // ------------------------------------------------------------------------
    // The SVG path length is 125.6 (half circumference of r=40).
    function setGaugeValue(pathEl, valEl, value) {
        // Clamp 0-100
        const safeVal = Math.max(0, Math.min(100, isNaN(value) ? 0 : value));

        // Dashoffset: 125.6 is empty (0%), 0 is full (100%)
        const offset = 125.6 - (safeVal / 100) * 125.6;
        pathEl.style.strokeDashoffset = offset;

        // Animate number
        let current = parseInt(valEl.innerText) || 0;
        const target = Math.round(safeVal);
        const duration = 1500;
        const steps = 30;
        const stepTime = duration / steps;
        const increment = (target - current) / steps;

        let stepCount = 0;
        const timer = setInterval(() => {
            current += increment;
            stepCount++;
            valEl.innerText = Math.round(current);
            if (stepCount >= steps) {
                valEl.innerText = target;
                clearInterval(timer);
            }
        }, stepTime);
    }

    // ------------------------------------------------------------------------
    // API Interaction (Analyze Activity)
    // ------------------------------------------------------------------------
    analyzeBtn.addEventListener('click', async function () {
        const q1 = document.getElementById('q1').value.trim();
        const q2 = document.getElementById('q2').value.trim();
        const q3 = document.getElementById('q3').value.trim();
        const q4 = document.getElementById('q4').value.trim();
        const q5 = document.getElementById('q5').value.trim();
        const q6 = document.getElementById('q6').value.trim();
        const q7 = document.getElementById('q7').value.trim();
        const q8 = document.getElementById('q8').value.trim();

        if (!q1) {
            document.getElementById('q1').classList.add('is-invalid');
            setTimeout(() => document.getElementById('q1').classList.remove('is-invalid'), 2000);
            return;
        }

        // Join answers into a descriptive paragraph for the AI
        const parts = [];
        parts.push(`Task led: ${q1}.`);
        if (q2) parts.push(`People coordinated: ${q2}.`);
        if (q3) parts.push(`Time spent: ${q3}.`);
        if (q4) parts.push(`Budget handled: ${q4}.`);
        if (q5) parts.push(`Supplies/Inventory managed: ${q5}.`);
        if (q6) parts.push(`Target audience/Beneficiaries: ${q6}.`);
        if (q7) parts.push(`Conflict handling approach: ${q7}.`);
        if (q8) parts.push(`Hardest part / Main Challenge: ${q8}.`);

        const text = parts.join(' ');

        // Loading State
        const originalText = this.innerHTML;
        this.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Analyzing...';
        this.disabled = true;

        try {
            const response = await fetch('/analyze_activity', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ activity: text })
            });

            const data = await response.json();

            if (response.ok) {
                // Remove empty state if present
                if (emptyFeedState) emptyFeedState.remove();

                // 1) Update Gauges
                setGaugeValue(leadershipPath, leadershipVal, data.leadership_index);
                setGaugeValue(employabilityPath, employabilityVal, data.skill_magnitude);

                // 2) Update 5-Point Radar Map Elements
                // We'll deterministically map the categories to our 5 points just for demo visually:
                // Strategic, Financial, Crisis, Team, Emotional
                const cat = data.leadership_category;
                const newBands = [...skillRadarChart.data.datasets[0].data];

                // Slowly decay old values, and spike the new one
                for (let i = 0; i < 5; i++) { newBands[i] = Math.max(15, newBands[i] * 0.7); }

                let targetIdx = 0;
                if (cat.includes("Strategic")) targetIdx = 0;
                else if (cat.includes("Resource") || cat.includes("Decision")) targetIdx = 1;
                else if (cat.includes("Crisis")) targetIdx = 2;
                else if (cat.includes("Coordination")) targetIdx = 3;
                else targetIdx = 4; // Emotion/Development

                newBands[targetIdx] = Math.min(100, data.skill_magnitude + 15);

                skillRadarChart.data.datasets[0].data = newBands;
                skillRadarChart.update();

                // 3) Push to Resume Feed
                const bgClass = ['bg-primary', 'bg-secondary', 'bg-success', 'bg-danger', 'bg-info'][Math.floor(Math.random() * 5)];
                const skillsHtml = (data.skills_mapped || ['Project Management']).map(s =>
                    `<span class="skill-badge me-1 mb-1 d-inline-block ${bgClass}">${s}</span>`
                ).join('');

                const df = document.createDocumentFragment();
                const div = document.createElement('div');
                div.className = 'feed-item';
                div.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="fw-bold text-primary small"><i class="bi bi-briefcase-fill me-1"></i> ${data.transferable_skill}</span>
                        <span class="badge bg-light text-dark border">${data.market_value} Value</span>
                    </div>
                    <div class="feed-bullet mb-2">${data.resume_snippet}</div>
                    <div>${skillsHtml}</div>
                `;

                df.appendChild(div);
                resumeFeedContainer.prepend(df);

                // 5) Render Smart Matches (deduplicated by title)
                if (data.matches && data.matches.length > 0) {
                    const smContainer = document.getElementById('smartMatchesContainer');
                    const smRow = document.getElementById('smartMatchesRow');
                    if (smContainer && smRow) {
                        smContainer.style.display = 'block';
                        const colours = ['text-primary', 'text-success', 'text-warning', 'text-info-emphasis'];

                        data.matches.forEach((m, idx) => {
                            // Deduplicate by title across all renders on this page
                            if (window._seenMatchTitles && window._seenMatchTitles.has(m.title)) return;
                            if (!window._seenMatchTitles) window._seenMatchTitles = new Set();
                            window._seenMatchTitles.add(m.title);

                            const pct = m.match_percentage || 75;
                            let badgeCls = 'bg-success';
                            if (pct < 70) badgeCls = 'bg-warning text-dark';
                            if (pct < 60) badgeCls = 'bg-secondary';
                            const col = colours[idx % colours.length];

                            const card = document.createElement('div');
                            card.className = 'col-md-6';
                            card.innerHTML = `
                                <div class="card h-100 border-0 shadow-sm glass-card hover-lift animated-card" style="animation-delay: ${0.1 + idx * 0.2}s;">
                                    <div class="card-body p-4">
                                        <div class="d-flex justify-content-between align-items-start mb-3">
                                            <h6 class="fw-bold ${col} mb-0"><i class="bi bi-person-check-fill me-2"></i>${m.title}</h6>
                                            <span class="badge ${badgeCls} rounded-pill px-3"><i class="bi bi-bullseye me-1"></i>${pct}% Match</span>
                                        </div>
                                        <p class="small text-muted mb-3"><i class="bi bi-info-circle me-1 text-primary"></i>${m.why_it_fits}</p>
                                        <div class="p-2 rounded-3" style="background: rgba(99,102,241,0.06);">
                                            <p class="small fw-semibold mb-0"><i class="bi bi-arrow-right-circle-fill text-primary me-1"></i>${m.action_step}</p>
                                        </div>
                                    </div>
                                </div>`;
                            smRow.appendChild(card);
                        });
                    }
                }

                // 4) Update Opportunity Engine
                // -------------------------------------------------------------------
                // Read from guaranteed top-level flat keys first (set by backend),
                // then fall back to nested market_opportunities as a second safety net.
                // -------------------------------------------------------------------
                const opps = (data.market_opportunities && typeof data.market_opportunities === 'object')
                    ? data.market_opportunities
                    : {};

                const startupText = String(data.startup_idea || opps.startup_idea || "Analyzing your activity...");
                const startupBudget = String(data.startup_budget || opps.startup_budget || "₹10,000 – ₹25,000");
                const collabText = String(data.collaboration_match || opps.collaboration_match || "Generating your match...");
                const jobRoleText = String(data.job_role || opps.job_role || "Public Health Outreach Coordinator");

                // Growth Card — flat keys are guaranteed non-empty from backend
                const skillToLearn = String(data.growth_skill || (data.learning_path && data.learning_path.skill_to_learn) || "Digital Literacy & Community Health Communication");
                const freeResource = String((data.learning_path && data.learning_path.free_resource) || "Google Digital Garage on YouTube");
                const dailyGoal = String((data.learning_path && data.learning_path.daily_goal) || "Watch a 10-minute video today");
                const learningUrl = String(data.learning_url || opps.learning_url || "https://www.youtube.com/watch?v=Xv1tM_pX22Y");

                // Populate Dynamic Business Roadmap Modal
                const industryName = data.industry || "Business";
                const bpModalLabel = document.getElementById('businessPlanModalLabel');
                if (bpModalLabel) {
                    bpModalLabel.innerHTML = `<i class="bi bi-rocket-takeoff-fill text-success me-2"></i>Your 3-Step ${industryName} Roadmap`;
                }

                if (opps.business_roadmap && Array.isArray(opps.business_roadmap)) {
                    opps.business_roadmap.forEach((stepObj, idx) => {
                        const stepNum = idx + 1;
                        if (stepNum <= 3) {
                            const titleEl = document.getElementById(`bp-step${stepNum}-title`);
                            const descEl = document.getElementById(`bp-step${stepNum}-desc`);
                            if (titleEl) titleEl.innerText = stepObj.title || `Step ${stepNum}`;
                            if (descEl) descEl.innerText = stepObj.desc || "Action details pending...";
                        }
                    });
                }

                // Populate Dynamic Pitch Email Modal
                if (opps.pitch_email && typeof opps.pitch_email === 'object') {
                    const subjectEl = document.getElementById('pitch-subject');
                    const bodyEl = document.getElementById('pitch-body');
                    if (subjectEl) subjectEl.innerText = opps.pitch_email.subject || "Partnership Proposal";
                    if (bodyEl) bodyEl.innerText = opps.pitch_email.body || "I would love to discuss a potential partnership based on my recent community operations experience. Please let me know if you are open to a brief call.";
                }

                const oppContainer = document.getElementById('opportunityEngineContainer');
                const oppRow = document.getElementById('opportunitiesRow');
                oppContainer.style.display = 'flex';

                const matchScore = data.employability_score || 70;
                let badgeClass = 'bg-success';
                if (matchScore < 60) badgeClass = 'bg-warning text-dark';
                if (matchScore < 40) badgeClass = 'bg-secondary';

                const i18n = window.OPP_I18N || {
                    startup: "Startup Idea", collab: "Collaboration Match", jobRoles: "Job Role", growth: "Growth Plan",
                    match: "Match", btnStart: "Learn How to Start", btnPitch: "Pitch This Partner", btnDetails: "View Openings", btnLearn: "Start Learning"
                };

                // Populate Voice Assistant Speech Text
                window.aiSpeechText = `${i18n.startup}: ${startupText}. ${i18n.jobRoles}: ${jobRoleText}.`;

                // Update and show WhatsApp Share Button
                const waBtn = document.getElementById('whatsappShareBtn');
                if (waBtn) {
                    const shareText = `Hi, I just mapped my professional skills using ISIS! I am a ${matchScore}% match for ${jobRoleText}. Check out my open opportunities here: ${window.location.origin}`;
                    waBtn.href = `https://api.whatsapp.com/send?text=${encodeURIComponent(shareText)}`;
                    waBtn.classList.remove('d-none');
                }


                const badgeHtml = `<span class="badge ${badgeClass} float-end rounded-pill px-2 py-1 animated-badge"><i class="bi bi-bullseye me-1"></i>${matchScore}% ${i18n.match}</span>`;

                oppRow.innerHTML = `
                    <div class="col-lg-3 col-md-6 mb-4 mb-lg-0">
                        <div class="card h-100 border-0 shadow-sm glass-card hover-lift animated-card d-flex flex-column" style="animation-delay: 0.1s;">
                            <div class="card-body flex-grow-1">
                                ${badgeHtml}
                                <h6 class="text-success fw-bold"><i class="bi bi-rocket-takeoff-fill me-2"></i>${i18n.startup || "Startup Idea"}</h6>
                                <p class="small text-muted mt-2 mb-2" id="opp-startup">${startupText}</p>
                                <div class="d-flex align-items-center gap-1 mt-1">
                                    <i class="bi bi-currency-rupee text-success" style="font-size:0.75rem;"></i>
                                    <span class="badge rounded-pill fw-semibold" style="background:rgba(25,135,84,0.12);color:#198754;font-size:0.7rem;">Est. Budget: ${startupBudget}</span>
                                </div>
                            </div>
                            <div class="card-footer bg-transparent border-0 pt-0 pb-3 px-3">
                                <button id="btn-learn-startup" class="btn btn-sm btn-outline-success w-100 rounded-pill"><i class="bi bi-arrow-right-circle me-1"></i>${i18n.btnStart || "Learn How to Start"}</button>
                            </div>
                        </div>
                    </div>
                    <div class="col-lg-3 col-md-6 mb-4 mb-lg-0">
                        <div class="card h-100 border-0 shadow-sm glass-card hover-lift animated-card d-flex flex-column" style="animation-delay: 0.2s;">
                            <div class="card-body flex-grow-1">
                                ${badgeHtml}
                                <h6 class="text-primary fw-bold"><i class="bi bi-people-fill me-2"></i>${i18n.collab || "Collaboration Match"}</h6>
                                <p class="small text-muted mt-2 mb-0" id="opp-collab">${collabText}</p>
                            </div>
                            <div class="card-footer bg-transparent border-0 pt-0 pb-3 px-3">
                                <button id="btn-draft-pitch" class="btn btn-sm btn-outline-primary w-100 rounded-pill"><i class="bi bi-envelope-paper-fill me-1"></i>${i18n.btnPitch || "Pitch This Partner"}</button>
                            </div>
                        </div>
                    </div>
                    <div class="col-lg-3 col-md-6 mb-4 mb-lg-0">
                        <div class="card h-100 border-0 shadow-sm glass-card hover-lift animated-card d-flex flex-column" style="animation-delay: 0.3s;">
                            <div class="card-body flex-grow-1">
                                ${badgeHtml}
                                <h6 class="text-info-emphasis fw-bold"><i class="bi bi-person-badge-fill me-2"></i>${i18n.jobRoles || "Job Role"}</h6>
                                <p class="small text-muted mt-2 mb-0" id="opp-job">${jobRoleText}</p>
                            </div>
                            <div class="card-footer bg-transparent border-0 pt-0 pb-3 px-3">
                                <button id="btn-view-openings" class="btn btn-sm btn-outline-info w-100 rounded-pill" title="Searching LinkedIn for you..." style="color:var(--bs-info-text,#055160);border-color:var(--bs-info-border,#b6effb);"><i class="bi bi-search me-1"></i>${i18n.btnDetails || "View Openings"}</button>
                            </div>
                        </div>
                    </div>
                    <!-- NEW: Upskilling Recommendation 'Growth Card' -->
                    <div class="col-lg-3 col-md-6 mb-4 mb-lg-0">
                        <div class="card h-100 border-0 shadow-sm glass-card hover-lift animated-card d-flex flex-column" style="animation-delay: 0.4s;">
                            <div class="card-body flex-grow-1">
                                ${badgeHtml}
                                <h6 class="text-warning fw-bold"><i class="bi bi-lightning-charge-fill me-2"></i>${i18n.growth || "Growth Plan"}</h6>
                                <p class="small text-dark fw-bold mt-2 mb-1">${skillToLearn}</p>
                                <p class="small text-muted mb-2"><i class="bi bi-journal-bookmark text-primary me-1"></i>${freeResource}</p>
                                <div class="p-2 rounded-3" style="background: rgba(255, 193, 7, 0.1);">
                                    <p class="small fw-semibold mb-0 text-warning-emphasis"><i class="bi bi-clock-history me-1"></i>${dailyGoal}</p>
                                </div>
                            </div>
                            <div class="card-footer bg-transparent border-0 pt-0 pb-3 px-3">
                                <button id="btn-start-learning" title="Searching YouTube for you..." class="btn btn-sm btn-outline-warning w-100 rounded-pill"><i class="bi bi-play-circle-fill me-1"></i>${i18n.btnLearn || "Start Learning"}</button>
                            </div>
                        </div>
                    </div>
                `;

                // ----------------------------------------------------------------
                // Action Trigger: Wire button events after innerHTML is injected
                // ----------------------------------------------------------------
                // 1) 'Learn How to Start' → opens 3-step Business Plan popup
                const btnLearnStartup = document.getElementById('btn-learn-startup');
                if (btnLearnStartup) {
                    btnLearnStartup.addEventListener('click', () => {
                        const modal = new bootstrap.Modal(document.getElementById('businessPlanModal'));
                        modal.show();
                    });
                }

                // 2) 'Draft a Pitch' → opens pre-filled email template popup
                const btnDraftPitch = document.getElementById('btn-draft-pitch');
                if (btnDraftPitch) {
                    btnDraftPitch.addEventListener('click', () => {
                        const modal = new bootstrap.Modal(document.getElementById('pitchModal'));
                        modal.show();
                    });
                }

                // 3) 'View Openings' → opens the LinkedIn search URL
                const btnViewOpenings = document.getElementById('btn-view-openings');
                if (btnViewOpenings) {
                    btnViewOpenings.addEventListener('click', () => {
                        if (data.job_link) {
                            window.open(data.job_link, '_blank');
                        }
                    });
                }

                // 4) 'Start Learning' → uses the dynamic YouTube search URL from backend
                const btnStartLearning = document.getElementById('btn-start-learning');
                if (btnStartLearning) {
                    btnStartLearning.addEventListener('click', () => {
                        if (data.learning_link) {
                            window.open(data.learning_link, '_blank');
                        } else {
                            // Sub-fallback if old backend response format
                            const watchUrl = learningUrl.replace('/embed/', '/watch?v=');
                            window.open(watchUrl, '_blank');
                        }
                    });
                }

                // 5) 'Copy' button in Pitch Modal → copies email body to clipboard
                const copyPitchBtn = document.getElementById('copyPitchBtn');
                if (copyPitchBtn) {
                    copyPitchBtn.addEventListener('click', () => {
                        const pitchText = document.getElementById('pitchEmailBody')?.innerText || '';
                        navigator.clipboard.writeText(pitchText).then(() => {
                            copyPitchBtn.innerHTML = '<i class="bi bi-clipboard-check me-1"></i>Copied!';
                            copyPitchBtn.classList.replace('btn-outline-secondary', 'btn-success');
                            setTimeout(() => {
                                copyPitchBtn.innerHTML = '<i class="bi bi-clipboard me-1"></i>Copy';
                                copyPitchBtn.classList.replace('btn-success', 'btn-outline-secondary');
                            }, 2000);
                        });
                    });
                }

                // Inputs are no longer cleared so the user can go back and edit them later.

                this.innerHTML = '<i class="bi bi-check2-circle me-2"></i>Analyzed';
                this.classList.replace('btn-primary', 'btn-success');

                // Transition to Step 2
                setTimeout(() => {
                    step1.style.display = 'none';
                    step2.style.display = 'block';
                    this.innerHTML = originalText;
                    this.classList.replace('btn-success', 'btn-primary');
                    this.disabled = false;
                }, 1000);

            } else {
                alert(`Error: ${data.message}`);
                this.innerHTML = originalText;
                this.disabled = false;
            }

        } catch (error) {
            console.error(error);
            alert("Network error connecting to Backend.");
            this.innerHTML = originalText;
            this.disabled = false;
        }
    });

    // ------------------------------------------------------------------------
    // Wizard Navigation Event Listeners
    // ------------------------------------------------------------------------

    if (backToStep1Btn) {
        backToStep1Btn.addEventListener('click', () => {
            step2.style.display = 'none';
            step1.style.display = 'flex';
        });
    }

    if (backToStep2Btn) {
        backToStep2Btn.addEventListener('click', () => {
            step3.style.display = 'none';
            step2.style.display = 'block';
        });
    }

    if (goToStep3Btn) {
        goToStep3Btn.addEventListener('click', () => {
            step2.style.display = 'none';
            step3.style.display = 'block';
        });
    }

    if (restartWizardBtn) {
        restartWizardBtn.addEventListener('click', () => {
            step3.style.display = 'none';

            // Clear inputs ONLY on full Start Over
            document.getElementById('q1').value = '';
            document.getElementById('q2').value = '';
            document.getElementById('q3').value = '';
            document.getElementById('q4').value = '';

            step1.style.display = 'flex'; // It uses d-flex row classes usually
        });
    }

    // ------------------------------------------------------------------------
    // Initial Load - Fetch Dashboard Metrics to Animate Gauges & Load History
    // ------------------------------------------------------------------------
    fetch('/dashboard_metrics')
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                if (data.total_activities > 0 && emptyFeedState) {
                    emptyFeedState.remove();
                }

                // 1) Animate Gauges on load
                setGaugeValue(leadershipPath, leadershipVal, data.avg_leadership_index || 0);
                setGaugeValue(employabilityPath, employabilityVal, data.employability_score || 0);

                // 2) Initialize Radar Map Elements
                if (data.radar_averages) {
                    skillRadarChart.data.datasets[0].data = [
                        data.radar_averages['Strategic'] || 0,
                        data.radar_averages['Financial'] || 0,
                        data.radar_averages['Crisis'] || 0,
                        data.radar_averages['Team'] || 0,
                        data.radar_averages['Emotional'] || 0
                    ];
                    skillRadarChart.update();
                }

                // 3) Load recent activity bullets into the Feed
                if (data.recent_activities && data.recent_activities.length > 0) {
                    const df = document.createDocumentFragment();
                    data.recent_activities.forEach(act => {
                        const bgClass = ['bg-primary', 'bg-secondary', 'bg-success', 'bg-danger', 'bg-info'][Math.floor(Math.random() * 5)];
                        const skills = Array.isArray(act.skills_mapped) && act.skills_mapped.length > 0
                            ? act.skills_mapped
                            : ['Project Management'];

                        const skillsHtml = skills.map(s =>
                            `<span class="skill-badge me-1 mb-1 d-inline-block ${bgClass}">${s}</span>`
                        ).join('');

                        const badgeText = act.career_equivalency || (act.market_value ? act.market_value + ' Value' : 'Matched Position');
                        const snippet = act.resume_snippet || `Demonstrated expertise in ${act.mapped_skill}.`;

                        const div = document.createElement('div');
                        div.className = 'feed-item';
                        div.innerHTML = `
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <span class="fw-bold text-primary small"><i class="bi bi-briefcase-fill me-1"></i> ${act.mapped_skill}</span>
                                <span class="badge bg-light text-dark border">${badgeText}</span>
                            </div>
                            <div class="feed-bullet mb-2">${snippet}</div>
                            <div>${skillsHtml}</div>
                        `;
                        df.appendChild(div);
                    });
                    // Append instead of prepend since they are already ordered DESC by backend
                    resumeFeedContainer.appendChild(df);
                }
            }
        })
        .catch(err => console.error("Error fetching initial metrics:", err));

    // ------------------------------------------------------------------------
    // PDF Export — real jsPDF download to user's local Downloads folder
    // ------------------------------------------------------------------------
    downloadPdfBtn.addEventListener('click', async function () {
        const originalText = this.innerHTML;
        this.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating PDF...';
        this.disabled = true;

        try {
            const { jsPDF } = window.jspdf;
            const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });

            const margin = 18;
            const pageW = doc.internal.pageSize.getWidth();
            const usableW = pageW - margin * 2;
            let y = margin;

            const addLine = (text, fontSize, bold, color) => {
                doc.setFontSize(fontSize);
                doc.setFont('helvetica', bold ? 'bold' : 'normal');
                doc.setTextColor(...(color || [30, 41, 59]));
                doc.text(text, margin, y);
                y += fontSize * 0.45 + 3;
            };

            const addHRule = () => {
                doc.setDrawColor(203, 213, 225);
                doc.line(margin, y, pageW - margin, y);
                y += 5;
            };

            const checkPage = (needed = 12) => {
                if (y + needed > doc.internal.pageSize.getHeight() - margin) {
                    doc.addPage();
                    y = margin;
                }
            };

            // Cover Header
            doc.setFillColor(99, 102, 241);
            doc.rect(0, 0, pageW, 38, 'F');
            doc.setFontSize(22); doc.setFont('helvetica', 'bold'); doc.setTextColor(255, 255, 255);
            doc.text('Professional Portfolio', margin, 18);
            doc.setFontSize(10); doc.setFont('helvetica', 'normal');
            doc.text('Generated by ISIS \u2014 Invisible Skill Intelligence System', margin, 26);
            doc.text(new Date().toLocaleDateString('en-IN', { dateStyle: 'long' }), margin, 33);
            y = 48;

            // Core Metrics
            const li = parseInt(leadershipVal.innerText) || 0;
            const es = parseInt(employabilityVal.innerText) || 0;
            addLine('Core Metrics', 13, true, [99, 102, 241]);
            addHRule();
            doc.setFontSize(10); doc.setFont('helvetica', 'normal'); doc.setTextColor(30, 41, 59);
            doc.text(`Leadership Index:     ${li}/100`, margin, y); y += 7;
            doc.text(`Employability Score:  ${es}/100`, margin, y); y += 10;

            // 5-Point Radar as bar bands
            const radarLabels = ['Strategic', 'Financial', 'Crisis', 'Team', 'Emotional'];
            const radarData = skillRadarChart.data.datasets[0].data;
            if (radarData.some(v => v > 0)) {
                checkPage(30);
                addLine('5-Point Skill Map', 13, true, [99, 102, 241]);
                addHRule();
                radarLabels.forEach((lbl, i) => {
                    const val = Math.round(radarData[i] || 0);
                    doc.setFontSize(10); doc.setFont('helvetica', 'normal'); doc.setTextColor(30, 41, 59);
                    doc.text(`${lbl}:`, margin, y);
                    const barX = margin + 35;
                    const barW = (usableW - 42) * val / 100;
                    doc.setFillColor(230, 231, 255); doc.rect(barX, y - 4, usableW - 42, 5, 'F');
                    doc.setFillColor(99, 102, 241); doc.rect(barX, y - 4, barW, 5, 'F');
                    doc.text(`${val}`, pageW - margin - 6, y);
                    y += 9;
                });
                y += 4;
            }

            // Resume Bullets  — deduplicated & capped to 5 unique entries
            const feedItems = document.querySelectorAll('.feed-item');
            if (feedItems.length > 0) {
                checkPage(20);
                addLine('Resume Bullets', 13, true, [99, 102, 241]);
                addHRule();

                // Collect items, dedup by bullet text, keep latest 5
                const seenBullets = new Set();
                const uniqueItems = [];
                feedItems.forEach(item => {
                    const bullet = item.querySelector('.feed-bullet')?.innerText?.trim() || '';
                    if (bullet && !seenBullets.has(bullet)) {
                        seenBullets.add(bullet);
                        uniqueItems.push(item);
                    }
                });
                const topFive = uniqueItems.slice(0, 5);  // latest 5 unique

                topFive.forEach(item => {
                    checkPage(20);
                    const title = item.querySelector('.fw-bold')?.innerText?.trim() || '';
                    const bullet = item.querySelector('.feed-bullet')?.innerText?.trim() || '';
                    const badges = [...item.querySelectorAll('.skill-badge')].map(b => b.innerText.trim()).join('  \u00b7  ');
                    doc.setFontSize(10); doc.setFont('helvetica', 'bold'); doc.setTextColor(99, 102, 241);
                    doc.text(title, margin, y); y += 6;
                    doc.setFont('helvetica', 'normal'); doc.setTextColor(30, 41, 59);
                    const lines = doc.splitTextToSize(`\u2022 ${bullet}`, usableW);
                    doc.text(lines, margin, y); y += lines.length * 5 + 2;
                    if (badges) {
                        doc.setFontSize(8.5); doc.setTextColor(100, 116, 139);
                        doc.text(badges, margin, y); y += 8;
                    }
                    y += 2;
                });
            } else {
                checkPage(10);
                doc.setFontSize(10); doc.setTextColor(148, 163, 184);
                doc.text('No resume bullets yet. Analyze at least one activity first.', margin, y);
                y += 10;
            }

            // Page footers
            const totalPages = doc.internal.getNumberOfPages();
            for (let p = 1; p <= totalPages; p++) {
                doc.setPage(p);
                doc.setFontSize(8); doc.setFont('helvetica', 'normal'); doc.setTextColor(148, 163, 184);
                doc.text(`ISIS Professional Portfolio  \u00b7  Page ${p} of ${totalPages}`,
                    pageW / 2, doc.internal.pageSize.getHeight() - 8, { align: 'center' });
            }

            // Trigger real browser download via Blob and hidden Anchor
            const pdfBlob = doc.output('blob');
            const pdfUrl = URL.createObjectURL(pdfBlob);
            const a = document.createElement('a');
            a.href = pdfUrl;
            a.download = 'ISIS_Professional_Portfolio.pdf';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(pdfUrl), 100);

            this.innerHTML = '<i class="bi bi-check2 me-2"></i> Downloaded';
            this.classList.replace('btn-outline-primary', 'btn-success');
            setTimeout(() => {
                this.innerHTML = originalText;
                this.classList.replace('btn-success', 'btn-outline-primary');
            }, 3000);

        } catch (err) {
            console.error('PDF generation failed:', err);
            alert('PDF generation failed. Please check the browser console.');
            this.innerHTML = originalText;
        } finally {
            this.disabled = false;
        }
    });
});
