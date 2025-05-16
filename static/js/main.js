    // Código para esconder o Preloader

   window.addEventListener('load', () => {

     console.log("Evento LOAD disparado!"); // Log para depuração

     const preloader = document.getElementById('preloader');

     if (preloader) {

       console.log("Preloader encontrado, adicionando classe hidden..."); // Log para depuração

       preloader.classList.add('hidden');

     } else {

       console.error("Elemento #preloader NÃO encontrado!"); // Log de erro

     }

   });
  // Scroll
  const scrollThumb = document.getElementById('scrollThumb');
  window.addEventListener('scroll', () => {
    const scrollTop = window.scrollY;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    scrollThumb.style.height = `${(scrollTop / docHeight) * 100}%`;
  });

  // Ripple effect
  document.body.addEventListener("click", (e) => {
    const ripple = document.createElement("div");
    ripple.className = "ripple";
    Object.assign(ripple.style, {
      left: `${e.clientX}px`,
      top: `${e.clientY}px`
    });
    document.body.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
  });
  
