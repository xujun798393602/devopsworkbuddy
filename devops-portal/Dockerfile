ARG NGINX_IMAGE=nginx:alpine
FROM ${NGINX_IMAGE}
USER root
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chmod -R a-w /usr/share/nginx/html \
    && chown -R nginx:nginx /var/cache/nginx /var/run /etc/nginx/conf.d
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/health"]
