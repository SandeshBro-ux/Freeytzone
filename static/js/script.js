// YouTube Downloader Frontend Script
console.log("static/js/script.js loaded");

document.addEventListener('DOMContentLoaded', function() {
    console.log("DOMContentLoaded event fired");
    // DOM Elements
    const youtubeUrlInput = document.getElementById('youtube-url');
    const fetchInfoBtn = document.getElementById('fetch-info-btn');
    const videoInfoCard = document.getElementById('video-info-card');
    const videoTitle = document.getElementById('video-title');
    const videoUploader = document.getElementById('video-uploader');
    const videoViews = document.getElementById('video-views');
    const videoLikes = document.getElementById('video-likes');
    const channelSubscribers = document.getElementById('channel-subscribers');
    const thumbnailContainer = document.getElementById('thumbnail-container');
    const formatSelect = document.getElementById('format-select');
    const qualityContainer = document.getElementById('quality-container');
    const qualitySelect = document.getElementById('quality-select');
    const downloadBtn = document.getElementById('download-btn');
    const downloadProgressCard = document.getElementById('download-progress-card');
    const progressBar = document.getElementById('progress-bar');
    const downloadSpeed = document.getElementById('download-speed');
    const downloadEta = document.getElementById('download-eta');
    const cancelBtn = document.getElementById('cancel-btn');
    const downloadCompleteContainer = document.getElementById('download-complete-container');
    const downloadLink = document.getElementById('download-link');
    const newDownloadBtn = document.getElementById('new-download-btn');
    const downloadErrorContainer = document.getElementById('download-error-container');
    const errorMessage = document.getElementById('error-message');
    const retryBtn = document.getElementById('retry-btn');
    const bestQualityInfo = document.getElementById('best-quality-info');
    const newDownloadBtnError = document.getElementById('new-download-btn-error');
    const channelLogo = document.getElementById('channel-logo');

    // Log if critical elements are not found
    if (!youtubeUrlInput) console.error("youtubeUrlInput not found!");
    if (!fetchInfoBtn) console.error("fetchInfoBtn not found!");
    if (!videoInfoCard) console.error("videoInfoCard (video-info-card) not found!");
    if (!formatSelect) console.error("formatSelect not found!");
    if (!qualitySelect) console.error("qualitySelect not found!");
    if (!downloadBtn) console.error("downloadButton (download-btn) not found!");
    if (!bestQualityInfo) console.error("bestQualityInfo not found!");

    // State
    let currentVideoInfo = null;
    let currentDownloadId = null;
    let progressInterval = null;
    
    // Global variable to hold the YouTube IFrame API player instance
    let iframeApiPlayer = null;
    // Global variable to store the max quality label detected by the IFrame API
    let detectedMaxQualityLabelFromIframe = null;

    // Helper function to extract Video ID from YouTube URL
    function extractVideoId(url) {
        let videoId = null;
        const youtubeRegexPatterns = [
            /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|v\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/, // Standard, embed, shorts, youtu.be
            /(?:https?:\/\/)?(?:www\.)?youtube\.com\/live\/([a-zA-Z0-9_-]{11})/, // Live URLs
            /youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})/ // another shorts variant
        ];
        for (const pattern of youtubeRegexPatterns) {
            const match = url.match(pattern);
            if (match && match[1]) {
                videoId = match[1];
                break;
            }
        }
        console.log(`Extracted videoId: ${videoId} from URL: ${url}`);
        return videoId;
    }

    // Add event listener for the Fetch Info button
    if (fetchInfoBtn) {
        fetchInfoBtn.addEventListener('click', function() {
            console.log("Fetch Info button clicked");
            const url = youtubeUrlInput.value.trim();
            if (url) {
                fetchVideoInfo(url);
            } else {
                alert("Please enter a YouTube URL."); 
                console.warn("YouTube URL input is empty.");
            }
        });
    } else {
        console.error("Fetch Info Button (fetch-info-btn) not found in the DOM!");
    }
    
    // Event listener for format select change (if it influences quality or UI)
    if (formatSelect) {
        formatSelect.addEventListener('change', updateQualityOptions); 
    }

    // Event listener for the main download button (assuming ID 'download-btn')
    if (downloadBtn) {
        downloadBtn.addEventListener('click', startDownload);
    } else {
        console.error("Download Button (download-btn) not found in the DOM!");
    }
    
    // Event listeners for other buttons if they exist (new download, retry, cancel)
    if (newDownloadBtn) {
        newDownloadBtn.addEventListener('click', resetUI);
    }
    if (newDownloadBtnError) {
        newDownloadBtnError.addEventListener('click', resetUI);
    }
    if (retryBtn) {
        retryBtn.addEventListener('click', () => {
            if (currentVideoInfo && currentVideoInfo.original_url) { // Assuming you store original_url
                startDownload(); // Retry last download
            } else {
                resetUI();
            }
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', cancelDownload);
    }

    // Promise that resolves when the YouTube IFrame API is ready
    const youtubeApiReadyPromise = new Promise(resolve => {
        if (typeof YT !== 'undefined' && YT.Player) {
            resolve(); // Already loaded
        } else {
            // This function will be called automatically by the YouTube IFrame API script
            window.onYouTubeIframeAPIReady = () => {
                resolve();
            };
        }
    });

    // Helper function to destroy the existing iframe player
    function destroyIframePlayer() {
        if (iframeApiPlayer) {
            try {
                iframeApiPlayer.stopVideo(); // Stop playback
                iframeApiPlayer.destroy();   // Destroy the player instance
            } catch (e) {
                console.error("Error destroying iframe player:", e);
            }
            iframeApiPlayer = null;
        }
        // Clear the container in case of leftover elements, though destroy() should handle it
        const playerContainer = document.getElementById('iframe-player-container');
        if (playerContainer) {
            playerContainer.innerHTML = ''; 
        }
    }

    // Function to get video quality using the IFrame API
    function getQualityViaIframeAPI(videoId) {
        return new Promise(async (resolve, reject) => {
            await youtubeApiReadyPromise; // Ensure API is ready

            destroyIframePlayer(); // Clean up any previous player

            const timeoutDuration = 15000; // 15 seconds timeout for quality detection
            let qualityDetectionTimeout = setTimeout(() => {
                console.warn('YouTube IFrame API quality detection timed out.');
                destroyIframePlayer();
                reject('timeout');
            }, timeoutDuration);

            try {
                iframeApiPlayer = new YT.Player('iframe-player-container', {
                    height: '0', // Invisible
                    width: '0',  // Invisible
                    videoId: videoId,
                    playerVars: {
                        autoplay: 1,
                        mute: 1,
                        controls: 0, // No controls
                        disablekb: 1, // Disable keyboard controls
                        fs: 0, // No fullscreen button
                        iv_load_policy: 3, // Don't show annotations
                        modestbranding: 1, // Minimal YouTube branding
                        playsinline: 1 // Play inline on iOS
                    },
                    events: {
                        'onReady': function(event) {
                            // Player is ready, but we need to wait for 'playing' state
                            // Mute again just in case, though playerVar should handle it
                            event.target.mute(); 
                        },
                        'onStateChange': function(event) {
                            // YT.PlayerState.PLAYING is 1
                            if (event.data === YT.PlayerState.PLAYING) {
                                // Short delay to allow quality levels to populate
                                setTimeout(() => {
                                    if (!iframeApiPlayer) return; // Player might have been destroyed by timeout

                                    const levels = iframeApiPlayer.getAvailableQualityLevels();
                                    clearTimeout(qualityDetectionTimeout); // Clear the main timeout

                                    if (levels && levels.length > 0) {
                                        const maxQuality = levels[0]; // Highest quality is usually first
                                        console.log('Max Quality via IFrame API:', maxQuality);
                                        destroyIframePlayer();
                                        resolve(maxQuality); // e.g., "hd1080", "hd1440"
                                    } else {
                                        console.warn('No quality levels found via IFrame API.');
                                        destroyIframePlayer();
                                        resolve(null); // Resolve with null if no levels found
                                    }
                                }, 750); // Increased delay slightly
                            }
                        },
                        'onError': function(event) {
                            clearTimeout(qualityDetectionTimeout);
                            console.error('YouTube IFrame API Player Error:', event.data);
                            destroyIframePlayer();
                            reject('player_error_' + event.data);
                        }
                    }
                });
            } catch (error) {
                clearTimeout(qualityDetectionTimeout);
                console.error("Error initializing IFrame API player:", error);
                destroyIframePlayer();
                reject('init_error');
            }
        });
    }

    // Helper function to map YouTube API quality levels to friendly names
    function mapQualityToFriendlyName(qualityLevel) {
        if (!qualityLevel) return "Unknown";
        switch (qualityLevel) {
            case 'highres': return '8K'; // Or dynamically get resolution if possible
            case 'hd2880': return '5K';
            case 'hd2160': return '4K';
            case 'hd1440': return '2K';
            case 'hd1080': return 'Full HD';
            case 'hd720': return 'HD';
            case 'large': return '480p'; // SD
            case 'medium': return '360p'; // SD
            case 'small': return '240p'; // SD
            case 'tiny': return '144p'; // SD
            default:
                if (qualityLevel.startsWith('hd') && parseInt(qualityLevel.substring(2)) > 0) {
                    return qualityLevel.substring(2) + 'p';
                }
                return qualityLevel.charAt(0).toUpperCase() + qualityLevel.slice(1); // Capitalize
        }
    }

    // Format duration from seconds to MM:SS or HH:MM:SS
    function formatDuration(seconds) {
        if (!seconds) return '0:00';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        } else {
            return `${minutes}:${secs.toString().padStart(2, '0')}`;
        }
    }
    
    // Format view count with commas
    function formatViewCount(count) {
        if (!count) return '0 views';
        return `${count.toLocaleString()} views`;
    }
    
    // Reset the UI to initial state
    function resetUI() {
        youtubeUrlInput.value = '';
        videoInfoCard.classList.add('d-none');
        downloadProgressCard.classList.add('d-none');
        downloadCompleteContainer.classList.add('d-none');
        downloadErrorContainer.classList.add('d-none');
        thumbnailContainer.style.backgroundImage = '';
        thumbnailContainer.innerHTML = '<i class="bi bi-image text-secondary" style="font-size: 3rem;"></i>';
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
        
        // Clear intervals
        if (progressInterval) {
            clearInterval(progressInterval);
            progressInterval = null;
        }
        
        currentVideoInfo = null;
        currentDownloadId = null;
    }
    
    // Update the quality select based on format
    function updateQualityOptions() {
        const format = formatSelect.value;
        qualitySelect.innerHTML = ''; // Clear existing options
        
        if (!currentVideoInfo || !currentVideoInfo.formats || currentVideoInfo.formats.length === 0) {
            qualityContainer.classList.add('d-none');
            // Use the iframe detected quality for the main display text if available
            if (bestQualityInfo) {
                if (detectedMaxQualityLabelFromIframe) {
                    bestQualityInfo.textContent = `Max quality (IFrame): ${detectedMaxQualityLabelFromIframe}. No specific download formats found yet.`;
                } else {
                    bestQualityInfo.textContent = 'Format information unavailable.';
                }
            }
            // Add a default best option even if formats are missing, using iframe quality
            const bestFallbackOption = document.createElement('option');
            bestFallbackOption.value = 'best';
            bestFallbackOption.textContent = detectedMaxQualityLabelFromIframe 
                ? `Best Quality Available (${detectedMaxQualityLabelFromIframe})` 
                : 'Best Quality Available';
            if (detectedMaxQualityLabelFromIframe && (detectedMaxQualityLabelFromIframe.includes('2K') || detectedMaxQualityLabelFromIframe.includes('4K'))) {
                bestFallbackOption.textContent += ' ✨';
            }
            qualitySelect.appendChild(bestFallbackOption);
            
            // Add audio only as a fallback too
            const audioFallbackOption = document.createElement('option');
            audioFallbackOption.value = 'audio';
            audioFallbackOption.textContent = 'Audio Only (MP3)';
            qualitySelect.appendChild(audioFallbackOption);
            
            if (qualitySelect.options.length > 0) qualitySelect.selectedIndex = 0;
            return;
        }
        
        const infoSource = currentVideoInfo.info_source; 

        if (format === 'video') {
            qualityContainer.classList.remove('d-none');
            let videoFormats = [];
            let bestQualityText = detectedMaxQualityLabelFromIframe || 'Not available'; // Prioritize iframe detection
            let maxHeight = 0; 
            // Use iframe quality if available, otherwise calculate from formats
            let maxQualityLabel = detectedMaxQualityLabelFromIframe || "SD"; 

            if (infoSource === 'yt-dlp' || infoSource === 'browser+yt-dlp') {
                videoFormats = currentVideoInfo.formats.filter(fmt => 
                    fmt.resolution && fmt.resolution.includes('x') && !fmt.resolution.toLowerCase().includes('audio')
                );

                if (videoFormats.length > 0 && !detectedMaxQualityLabelFromIframe) { // Only recalculate if iframe didn't provide it
                    videoFormats.forEach(fmt => {
                        if (fmt.resolution && fmt.resolution.includes('x')) {
                            const height = parseInt(fmt.resolution.split('x')[1]);
                            if (height > maxHeight) maxHeight = height;
                        }
                    });
                    if (maxHeight >= 2160) maxQualityLabel = "4K";
                    else if (maxHeight >= 1440) maxQualityLabel = "2K";
                    else if (maxHeight >= 1080) maxQualityLabel = "Full HD";
                    else if (maxHeight >= 720) maxQualityLabel = "HD";
                    else maxQualityLabel = "SD";
                } else if (detectedMaxQualityLabelFromIframe) {
                    // If iframe provided quality, map it to a numeric height for consistency if needed later
                    // This part might be optional if maxQualityLabel is already sufficient
                    if (maxQualityLabel === "4K") maxHeight = 2160;
                    else if (maxQualityLabel === "2K") maxHeight = 1440;
                    else if (maxQualityLabel === "Full HD") maxHeight = 1080;
                    else if (maxQualityLabel === "HD") maxHeight = 720;
                    // ... and so on for other labels if you need maxHeight numerically
                }
                
                const bestOption = document.createElement('option');
                bestOption.value = 'best';
                bestOption.textContent = `Best Quality Available (${maxQualityLabel})`;
                if (['4K', '2K'].includes(maxQualityLabel) || maxHeight >=1440) { // Check both label and derived height
                    bestOption.textContent += ' ✨';
                }
                qualitySelect.appendChild(bestOption);
                
                // Ensure this part still works and sorts correctly
                videoFormats.sort((a, b) => { // Sort by height, then fps
                    const heightA = parseInt(a.resolution.split('x')[1]);
                    const heightB = parseInt(b.resolution.split('x')[1]);
                    if (heightB !== heightA) return heightB - heightA;
                    return (b.fps || 0) - (a.fps || 0);
                });

                videoFormats.forEach(fmt => {
                    const option = document.createElement('option');
                    option.value = fmt.format_id; // Use format_id for download request
                    
                    // Extract height from resolution (e.g., 1920x1080 -> 1080)
                    const height = parseInt(fmt.resolution.split('x')[1]);
                    
                    // Create a more user-friendly label with resolution type (4K, 2K, HD)
                    let qualityLabel = '';
                    if (height >= 2160) qualityLabel = '4K';
                    else if (height >= 1440) qualityLabel = '2K';
                    else if (height >= 1080) qualityLabel = 'Full HD';
                    else if (height >= 720) qualityLabel = 'HD';
                    else qualityLabel = 'SD';
                    
                    let label = `${qualityLabel} (${height}p)`;
                    if (fmt.fps && fmt.fps > 30) label += ` ${fmt.fps}fps`;
                    if (fmt.ext) label += ` - ${fmt.ext}`;
                    
                    option.textContent = label;
                    qualitySelect.appendChild(option);
                });

            } else { // API fallback or unknown source
                const apiVideoFormat = currentVideoInfo.formats.find(fmt => fmt.format_id && fmt.format_id.startsWith('best_video'));
                if (apiVideoFormat) {
                    const option = document.createElement('option');
                    option.value = 'best'; // API usually just gives one "best" video option

                    let apiQualityLabel = detectedMaxQualityLabelFromIframe;
                    if (!apiQualityLabel && apiVideoFormat.resolution && apiVideoFormat.resolution.includes('(')) {
                         const match = apiVideoFormat.resolution.match(/\\(([^)]+)\\)/);
                         if (match && match[1]) apiQualityLabel = mapQualityToFriendlyName(match[1].toLowerCase()); // Use map for consistency
                    }
                    if (!apiQualityLabel) apiQualityLabel = "Best Available";

                    option.textContent = `Best Quality Available (${apiQualityLabel})`;
                     if (['4K', '2K'].includes(apiQualityLabel) || (apiVideoFormat.height && apiVideoFormat.height >=1440) ) {
                        option.textContent += ' ✨';
                    }
                    qualitySelect.appendChild(option);
                    bestQualityText = apiQualityLabel; // Update bestQualityText from API if iframe failed
                }
            }
            // Update bestQualityInfo text based on the final maxQualityLabel
            if (bestQualityInfo) {
                if (maxQualityLabel && maxQualityLabel !== "Not available" && maxQualityLabel !== "Unknown") {
                    bestQualityInfo.textContent = `Maximum quality detected: ${maxQualityLabel}`;
                    if (['4K', '2K'].includes(maxQualityLabel) || maxHeight >= 1440) {
                         bestQualityInfo.innerHTML = `<strong class="text-success">High resolution ${maxQualityLabel} available!</strong>`;
                    }
            } else {
                    bestQualityInfo.textContent = 'Could not determine specific maximum quality from available formats.';
                }
            }

        } else if (format === 'audio') {
            qualityContainer.classList.add('d-none'); // Typically no quality selection for audio
            const audioFormat = currentVideoInfo.formats.find(fmt => 
                (fmt.format_id && fmt.format_id.includes('audio')) || (fmt.resolution && fmt.resolution.toLowerCase().includes('audio'))
            );
            if (bestQualityInfo) {
                if (audioFormat && audioFormat.note) {
                    bestQualityInfo.textContent = `Downloading audio: ${audioFormat.note}.`;
                } else if (audioFormat && audioFormat.resolution) {
                    bestQualityInfo.textContent = `Downloading audio: ${audioFormat.resolution}.`;
                } else {
                    bestQualityInfo.textContent = 'Audio will be downloaded in best available quality.';
                }
            }
        } else {
            qualityContainer.classList.add('d-none');
            if (bestQualityInfo) bestQualityInfo.textContent = '';
        }
    }
    
    // Helper function for fetch with timeout
    async function fetchWithTimeout(resource, options = {}, timeout = 30000) { // Default timeout 30 seconds
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), timeout);

        const response = await fetch(resource, {
            ...options,
            signal: controller.signal  
        });
        clearTimeout(id);
        return response;
    }

    async function fetchVideoInfo(url) {
        // Existing initial variable declarations (ensure all are here: videoInfoCard, qualitySelect, etc.)
        const videoInfoCard = document.getElementById('video-info-card');
        const qualitySelect = document.getElementById('quality-select');
        const downloadButton = document.getElementById('download-button');
        const bestQualityInfo = document.getElementById('best-quality-info'); 
        const formatSelect = document.getElementById('format-select');
        const qualityContainer = document.getElementById('quality-container');
        const submitButton = document.getElementById('fetch-info-btn'); 
        const urlInput = document.getElementById('youtube-url');

        // Reset UI elements
        videoInfoCard.innerHTML = '';
        videoInfoCard.classList.add('d-none');
        qualitySelect.innerHTML = '';
        if (downloadButton) downloadButton.disabled = true;
        if (bestQualityInfo) bestQualityInfo.textContent = '';
        if (qualityContainer) qualityContainer.classList.add('d-none');

        currentVideoInfo = null; 
        detectedMaxQualityLabelFromIframe = null; 

        let videoId = extractVideoId(url);
        if (!videoId) {
            displayError("Invalid YouTube URL or could not extract Video ID.");
            if (submitButton) submitButton.disabled = false;
            if (urlInput) urlInput.disabled = false;
            return;
        }
        
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
        }
        if (urlInput) urlInput.disabled = true;

        updateLoadingStatus('Initializing video data request...', true);
        if (bestQualityInfo) bestQualityInfo.textContent = 'Detecting maximum quality...';

        let iframeSuccess = false;
        try {
            updateLoadingStatus('Detecting max quality via IFrame API (max 15s)...', true);
            const iframeQualityCode = await getQualityViaIframeAPI(videoId); // Uses its own internal timeout
            if (iframeQualityCode) {
                iframeSuccess = true;
                detectedMaxQualityLabelFromIframe = mapQualityToFriendlyName(iframeQualityCode);
                updateBestQualityInfoText(detectedMaxQualityLabelFromIframe, 'iframe');
                updateQualityOptions(); 
                updateLoadingStatus(`Detected Max Quality: ${detectedMaxQualityLabelFromIframe}. Fetching full details (max 30s)...`, true);
            } else {
                updateBestQualityInfoText(null, 'iframe_failed_no_levels');
                updateLoadingStatus('IFrame API: No quality levels. Fetching details from backend (max 30s)...', true);
            }
        } catch (error) {
            console.warn('IFrame API quality detection failed:', error);
            let iframeErrorMsg = 'IFrame API error.';
            if (error === 'timeout') iframeErrorMsg = 'IFrame API timed out.';
            else if (typeof error === 'string' && error.startsWith('player_error')) iframeErrorMsg = `IFrame Player Error (Code: ${error.split('_')[2]})`;
            
            updateBestQualityInfoText(null, 'iframe_error', iframeErrorMsg);
            updateLoadingStatus(`${iframeErrorMsg} Proceeding to backend (max 30s)...`, true);
        }

        updateLoadingStatus(iframeSuccess ? `Fetching full format list (Max Quality: ${detectedMaxQualityLabelFromIframe})...` : 'Fetching all video details from backend (max 30s)...', true);
        
        try {
            // Use fetchWithTimeout for the backend call
            const backendTimeout = 30000; // 30 seconds for backend
            const backendResponse = await fetchWithTimeout(`/api/video_info?url=${encodeURIComponent(url)}`, {}, backendTimeout);
            
            if (!backendResponse.ok) {
                let errorMsg = `Backend Error: ${backendResponse.status} ${backendResponse.statusText}`;
                try {
                    const errData = await backendResponse.json();
                    errorMsg = errData.error || errorMsg;
                } catch (e) { /* Ignore if error response is not json */ }
                throw new Error(errorMsg);
            }

            const data = await backendResponse.json();
            currentVideoInfo = data;

            if (data.error) {
                throw new Error(data.error);
            }
            
            if (!data.formats || data.formats.length === 0) {
                // Even if formats are empty, we might have title/thumbnail etc.
                displayVideoDetails(data); // Display whatever info we got (title, thumbnail)
                updateQualityOptions(); // This will show iframe quality if available, or "no formats"
                if (bestQualityInfo && detectedMaxQualityLabelFromIframe) {
                     updateBestQualityInfoText(detectedMaxQualityLabelFromIframe, 'iframe');
                     bestQualityInfo.textContent += ". No specific download formats returned from backend.";
                } else if (bestQualityInfo) {
                     bestQualityInfo.textContent = "No downloadable formats found, though video info might be available.";
                }
                // Don't necessarily call displayError, as some info might be present
            } else {
                displayVideoDetails(data); 
                updateQualityOptions();    
                if (downloadButton) downloadButton.disabled = false;
                const loadingSpinnerContainer = document.getElementById('loading-spinner-container');
                if(loadingSpinnerContainer) loadingSpinnerContainer.innerHTML = ''; 
            }
            videoInfoCard.classList.remove('d-none');

        } catch (error) {
            console.error('Error fetching video info from backend:', error);
            let detailedErrorMessage = error.message || 'An unexpected error occurred while fetching backend data.';
            if (error.name === 'AbortError') {
                detailedErrorMessage = 'Backend request timed out (30 seconds). Please try again.';
            }
            displayError(detailedErrorMessage);
            if (iframeSuccess && (!currentVideoInfo || !currentVideoInfo.formats)) {
                updateQualityOptions(); 
            }
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = 'Fetch Info'; 
            }
            if (urlInput) urlInput.disabled = false;
            
            if (!currentVideoInfo && videoInfoCard.classList.contains('d-none') === false) {
                 if (!videoInfoCard.querySelector('.video-details-grid')) { 
                    // If still no content, ensure error or clear message is there
                    // displayError would have already run if backend error, otherwise, it means iframe also failed bad
                    if (!videoInfoCard.querySelector('.alert-danger')){
                         videoInfoCard.innerHTML = '<p class="text-warning text-center">Could not load full video information. IFrame detection may have provided partial quality info.</p>';
                    }
                 }
            }
        }
    }
    
    // Helper to update loading status in the videoInfoCard
    function updateLoadingStatus(message, showSpinner = true) {
        if (videoInfoCard) {
            videoInfoCard.classList.remove('d-none');
            videoInfoCard.innerHTML = getLoadingSpinnerHTML(message, showSpinner);
        }
    }
    
    // Helper to generate spinner HTML (centralized)
    function getLoadingSpinnerHTML(message, showSpinner = true) {
        let spinner = showSpinner ? '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>' : '';
        return `<div id="loading-spinner-container" class="text-center p-3">${spinner} <p class="mt-2 mb-0">${message}</p></div>`;
    }
    
    // Helper function to update the best quality information text element
    function updateBestQualityInfoText(qualityLabel, source, errorMsg = '') {
        if (!bestQualityInfo) return;

        if (source === 'iframe') {
            bestQualityInfo.textContent = `Max quality (IFrame): ${qualityLabel}`;
            if (['4K', '2K', '5K', '8K'].includes(qualityLabel) || (qualityLabel && qualityLabel.includes('p') && parseInt(qualityLabel) >= 1440)) {
                bestQualityInfo.innerHTML = `<strong class="text-success">High resolution ${qualityLabel} detected by IFrame!</strong> (Fetching full list...)`;
            }
        } else if (source === 'iframe_failed_no_levels') {
            bestQualityInfo.textContent = 'IFrame API: No quality levels found.';
        } else if (source === 'iframe_error') {
            bestQualityInfo.textContent = `IFrame API Error: ${errorMsg}`;
        } else if (source === 'backend') {
            // This part is now handled more directly in updateQualityOptions and displayVideoDetails
            // For example, if iframe worked, this text might already be set.
            // If iframe failed, then updateQualityOptions will set it based on backend data.
            if (qualityLabel && qualityLabel !== "Not available" && qualityLabel !== "Unknown") {
                bestQualityInfo.textContent = `Maximum quality (Backend): ${qualityLabel}`;
                if (['4K', '2K'].includes(qualityLabel) || (qualityLabel && qualityLabel.includes('p') && parseInt(qualityLabel) >= 1440)) {
                     bestQualityInfo.innerHTML = `<strong class="text-success">High resolution ${qualityLabel} available!</strong>`;
                }
            } else if (!detectedMaxQualityLabelFromIframe) { // Only show this if IFrame also failed
                bestQualityInfo.textContent = 'Could not determine specific maximum quality from available formats.';
            }
        }
    }
    
    // Modify displayError to also reset the loading spinner area
    function displayError(message) {
        if (videoInfoCard) {
            videoInfoCard.innerHTML = `<div class="alert alert-danger text-center" role="alert">${message}</div>`;
            videoInfoCard.classList.remove('d-none');
        }
        // Clear best quality info text on error too
        if (bestQualityInfo) bestQualityInfo.textContent = '';
    }
    
    // Start the download process
    function startDownload() {
        if (!currentVideoInfo) return;
        
        const url = youtubeUrlInput.value;
        const format = formatSelect.value;
        const quality = format === 'video' ? qualitySelect.value : 'best';
        
        // Hide video info and show progress
        videoInfoCard.classList.add('d-none');
        downloadProgressCard.classList.remove('d-none');
        downloadCompleteContainer.classList.add('d-none');
        downloadErrorContainer.classList.add('d-none');
        
        // Reset progress
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
        downloadSpeed.textContent = 'Speed: Calculating...';
        downloadEta.textContent = 'ETA: Calculating...';
        
        // Send download request
        fetch('/api/download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url, format, quality })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to start download');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Store download ID
            currentDownloadId = data.download_id;
            
            // Start progress tracking
            trackDownloadProgress();
        })
        .catch(error => {
            console.error('Error starting download:', error);
            showDownloadError(error.message);
        });
    }
    
    // Track download progress
    function trackDownloadProgress() {
        if (!currentDownloadId) return;
        if (progressInterval) clearInterval(progressInterval);
        let smoothProgress = 0;
        let smoothingInterval = null;
        progressInterval = setInterval(() => {
            fetch(`/api/progress/${currentDownloadId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.error) throw new Error(data.error);
                    let targetProgress = Math.round(data.progress);
                    // Smooth progress bar
                    if (targetProgress > smoothProgress) {
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        smoothingInterval = setInterval(() => {
                            if (smoothProgress < targetProgress) {
                                smoothProgress++;
                                progressBar.style.width = `${smoothProgress}%`;
                                progressBar.textContent = `${smoothProgress}%`;
                            } else {
                                clearInterval(smoothingInterval);
                            }
                        }, 20);
                    } else {
                        progressBar.style.width = `${targetProgress}%`;
                        progressBar.textContent = `${targetProgress}%`;
                        smoothProgress = targetProgress;
                    }
                    // Show speed
                    if (data.speed && data.speed !== 'N/A') {
                        downloadSpeed.textContent = `Speed: ${data.speed}`;
                    }
                    // ETA logic
                    if (data.eta && data.eta !== 'N/A' && data.eta !== '00:00' && data.eta !== 'Processing...') {
                        downloadEta.textContent = `ETA: ${data.eta}`;
                    } else if (data.status === 'processing') {
                        downloadEta.textContent = `ETA: Processing...`;
                    } else if (data.progress > 0 && data.progress < 100 && data.elapsed) {
                        const secondsRemaining = Math.round((data.elapsed / data.progress) * (100 - data.progress));
                        downloadEta.textContent = `ETA: ${formatDuration(secondsRemaining)}`;
                    } else {
                        downloadEta.textContent = `ETA: Calculating...`;
                    }
                    // Handle completion/failure
                    if (data.status === 'completed') {
                        clearInterval(progressInterval);
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        progressBar.style.width = `100%`;
                        progressBar.textContent = `100%`;
                        downloadComplete();
                    } else if (data.status === 'failed') {
                        clearInterval(progressInterval);
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        showDownloadError('Download failed');
                    } else if (data.status === 'canceled') {
                        clearInterval(progressInterval);
                        if (smoothingInterval) clearInterval(smoothingInterval);
                        showDownloadError('Download was canceled');
                    }
                })
                .catch(error => {
                    clearInterval(progressInterval);
                    if (smoothingInterval) clearInterval(smoothingInterval);
                    showDownloadError(error.message);
                });
        }, 500);
    }
    
    // Handle download completion
    function downloadComplete() {
        // Hide cancel button
        cancelBtn.classList.add('d-none');
        
        // Update link and show download complete UI
        downloadLink.href = `/api/download-file/${currentDownloadId}`;
        downloadCompleteContainer.classList.remove('d-none');
        // Automatically trigger download
        downloadLink.click();
    }
    
    // Show download error
    function showDownloadError(message) {
        downloadErrorContainer.classList.remove('d-none');
        errorMessage.textContent = message || 'An unknown error occurred';
        cancelBtn.classList.add('d-none');
    }
    
    // Cancel the current download
    function cancelDownload() {
        if (!currentDownloadId) return;
        
        fetch(`/api/cancel/${currentDownloadId}`, {
            method: 'POST'
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to cancel download');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Clear progress interval
            if (progressInterval) {
                clearInterval(progressInterval);
                progressInterval = null;
            }
            
            showDownloadError('Download canceled');
        })
        .catch(error => {
            console.error('Error canceling download:', error);
        });
    }
});
