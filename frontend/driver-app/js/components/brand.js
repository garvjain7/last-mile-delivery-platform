export function brandMark(className = "brand-mark") {
    return `<span class="${className}" aria-hidden="true">
        <svg class="brand-glyph" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="2" width="60" height="60" rx="19" fill="#EDF4E7"/>
            <path d="M10 47h12c7 0 10-4 10-10v-4c0-6 4-10 10-10h5" stroke="#6F9957" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M11 47h11" stroke="#274436" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M30 37v-4m8-10h4" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M8 31h21v13H8z" fill="#fff" stroke="#274436" stroke-width="2.5" stroke-linejoin="round"/>
            <path d="M29 35h8l5 5v4H29V35Z" fill="#B8ED65" stroke="#274436" stroke-width="2.5" stroke-linejoin="round"/>
            <circle cx="15" cy="46" r="3.3" fill="#274436"/>
            <circle cx="35" cy="46" r="3.3" fill="#274436"/>
            <path d="M47 7c-6 0-10 4.5-10 10 0 7 10 16 10 16s10-9 10-16c0-5.5-4-10-10-10Z" fill="#B8ED65" stroke="#274436" stroke-width="2.8" stroke-linejoin="round"/>
            <circle cx="47" cy="17" r="3" fill="#274436"/>
        </svg>
    </span>`;
}
