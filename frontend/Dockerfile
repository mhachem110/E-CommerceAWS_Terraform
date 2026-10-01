FROM nginx:1.28-alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html styles.css app.js /usr/share/nginx/html/
EXPOSE 8080
