FROM nginx:1.27-alpine

COPY NEWWEB/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY NEWWEB/frontend /usr/share/nginx/html

EXPOSE 80
