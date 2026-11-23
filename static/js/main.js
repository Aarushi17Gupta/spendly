// main.js — students will add JavaScript here as features are built

// ------------------------------------------------------------------ //
// Landing page: "See how it works" video modal                        //
// ------------------------------------------------------------------ //

(function () {
    const modal = document.getElementById('videoModal');
    if (!modal) return;  // main.js runs on every page; only the landing page has the modal

    const videoFrame = document.getElementById('demoVideo');
    const closeBtn = modal.querySelector('.video-modal-close');
    const overlay = modal.querySelector('.video-modal-overlay');

    // Placeholder — replace with the real embed URL (https://www.youtube.com/embed/VIDEO_ID)
    const videoUrl = 'https://www.youtube.com/embed/dQw4w9WgXcQ';

    const seeHowBtn = Array.from(document.querySelectorAll('.hero-actions a')).find(
        btn => btn.textContent.includes('See how it works')
    );

    function isOpen() {
        return !modal.classList.contains('video-modal-hidden');
    }

    function openModal(e) {
        e.preventDefault();
        videoFrame.src = videoUrl;
        modal.classList.remove('video-modal-hidden');
    }

    function closeModal() {
        modal.classList.add('video-modal-hidden');
        videoFrame.src = '';  // unloading the iframe stops playback
    }

    if (seeHowBtn) {
        seeHowBtn.addEventListener('click', openModal);
    }

    closeBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', closeModal);

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && isOpen()) {
            closeModal();
        }
    });
})();
