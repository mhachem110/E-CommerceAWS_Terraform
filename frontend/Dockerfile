FROM nginx:1.30.5-alpine
RUN apk upgrade --no-cache
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY 05-dns-resolver.envsh /docker-entrypoint.d/05-dns-resolver.envsh
RUN chmod +x /docker-entrypoint.d/05-dns-resolver.envsh
COPY index.html styles.css app.js /usr/share/nginx/html/
EXPOSE 8080
